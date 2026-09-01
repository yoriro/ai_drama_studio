from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID, uuid4, uuid5

from app.tasks.queue import normalize_request_id


GEN_CLIP_VIDEO_NAMESPACE = UUID("17c124be-f03e-5a69-b4e5-e3a63f62994b")
_SEED_MASK = 0x7FFF_FFFF_FFFF_FFFF
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
_REQUIRED_PLACEHOLDERS = frozenset(
    {"shots", "references", "style", "requested_duration", "user_note"}
)
_REFERENCE_TYPES = frozenset({"character", "scene"})
_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SHOT_SNAPSHOT_FIELDS = (
    "id",
    "order",
    "duration_est",
    "shot_type",
    "camera",
    "description",
    "dialogue",
    "revision",
    "asset_ids",
)
_SHOT_PROMPT_FIELDS = (
    "order",
    "duration_est",
    "shot_type",
    "camera",
    "description",
    "dialogue",
)
_REFERENCE_FIELDS = (
    "slot_no",
    "reference_name",
    "asset_type",
    "asset_name",
    "asset_description",
    "image_source",
    "image_id",
    "override_sha256",
)
_REFERENCE_PROMPT_FIELDS = (
    "slot_no",
    "reference_name",
    "asset_type",
    "asset_name",
    "asset_description",
    "image_source",
)
_C009_REFERENCE_COUNT = 9
_C009_PATH_FORBIDDEN = frozenset("*[]|?")


MINIMAXH3_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ClipVideoReferences:
    references: tuple[dict[str, object], ...]
    reference_media: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ClipVideoIdentifiers:
    seed: int
    comfy_prompt_id: str


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise ValueError(f"{field} must be an array")
    return value


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _require_text(value: object, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        suffix = "non-empty " if not allow_empty else ""
        raise ValueError(f"{field} must be {suffix}text")
    return value


def _require_duration(value: object, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    if not math.isfinite(float(value)) or not 1 <= float(value) <= 5:
        raise ValueError(f"{field} must be between 1 and 5")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be 64 lowercase hexadecimal characters")
    return value


def _safe_image_path(value: object, field: str) -> tuple[str, str]:
    path = _require_text(value, field, allow_empty=False)
    if "\x00" in path or "\\" in path:
        raise ValueError(f"{field} must be a safe relative path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ValueError(f"{field} must be a safe relative path")
    extension = parsed.suffix.removeprefix(".").lower()
    if extension not in _IMAGE_EXTENSIONS:
        raise ValueError(f"{field} must use a supported image extension")
    return path, extension


def _shot_snapshot(value: object, field: str) -> dict[str, object]:
    shot = _require_mapping(value, field)
    if set(shot) != set(_SHOT_SNAPSHOT_FIELDS):
        raise ValueError(f"{field} has invalid snapshot fields")
    asset_ids_value = _require_sequence(shot["asset_ids"], f"{field}.asset_ids")
    asset_ids = [
        _require_positive_int(item, f"{field}.asset_ids[{index}]")
        for index, item in enumerate(asset_ids_value)
    ]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError(f"{field}.asset_ids must be unique")
    return {
        "id": _require_positive_int(shot["id"], f"{field}.id"),
        "order": _require_positive_int(shot["order"], f"{field}.order"),
        "duration_est": _require_duration(
            shot["duration_est"], f"{field}.duration_est"
        ),
        "shot_type": _require_text(shot["shot_type"], f"{field}.shot_type"),
        "camera": _require_text(shot["camera"], f"{field}.camera"),
        "description": _require_text(
            shot["description"], f"{field}.description"
        ),
        "dialogue": _require_text(shot["dialogue"], f"{field}.dialogue"),
        "revision": _require_nonnegative_int(
            shot["revision"], f"{field}.revision"
        ),
        "asset_ids": sorted(asset_ids),
    }


def _raw_shot_snapshot(value: object, field: str) -> tuple[int, dict[str, object]]:
    raw = _require_mapping(value, field)
    if set(raw) != set(_SHOT_SNAPSHOT_FIELDS) | {"position"}:
        raise ValueError(f"{field} has invalid raw snapshot fields")
    position = _require_positive_int(raw["position"], f"{field}.position")
    snapshot = _shot_snapshot(
        {name: raw[name] for name in _SHOT_SNAPSHOT_FIELDS}, field
    )
    return position, snapshot


def build_clip_video_shot_snapshots(
    shots: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Build full shot snapshots ordered by their clip position."""

    raw_shots = _require_sequence(shots, "shots")
    normalized: list[tuple[int, dict[str, object]]] = []
    positions: set[int] = set()
    for index, raw_value in enumerate(raw_shots):
        position, snapshot = _raw_shot_snapshot(raw_value, f"shots[{index}]")
        if position in positions:
            raise ValueError(f"shots position {position} must be unique")
        positions.add(position)
        normalized.append((position, snapshot))
    normalized.sort(key=lambda item: item[0])
    return tuple(snapshot for _, snapshot in normalized)


def project_clip_video_shots(
    shots: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Project full snapshots to the fields allowed in the prompt."""

    snapshots = _require_sequence(shots, "shots")
    projected: list[dict[str, object]] = []
    for index, value in enumerate(snapshots):
        snapshot = _shot_snapshot(value, f"shots[{index}]")
        projected.append(
            {field: snapshot[field] for field in _SHOT_PROMPT_FIELDS}
        )
    return tuple(projected)


def _reference_media(
    *, path: object, digest: object, field: str
) -> dict[str, object]:
    relative_path, extension = _safe_image_path(path, f"{field}.file_path")
    return {
        "file_path": relative_path,
        "extension": extension,
        "sha256": _require_sha256(digest, f"{field}.sha256"),
    }


def _asset_snapshot(
    value: object, *, field: str, expected_id: int
) -> tuple[str, str, str, int]:
    asset = _require_mapping(value, field)
    asset_id = _require_positive_int(asset.get("id"), f"{field}.id")
    if asset_id != expected_id:
        raise ValueError(f"{field}.id does not match slot asset_id")
    asset_type = _require_text(asset.get("type"), f"{field}.type")
    if asset_type not in _REFERENCE_TYPES:
        raise ValueError(f"{field}.type must be character or scene")
    name = _require_text(asset.get("name"), f"{field}.name")
    description = _require_text(asset.get("description"), f"{field}.description")
    revision = _require_nonnegative_int(asset.get("revision"), f"{field}.revision")
    return asset_type, name, description, revision


def build_clip_video_references(
    slots: Sequence[Mapping[str, object]],
) -> ClipVideoReferences:
    """Serialize enabled slots and resolve their immutable media identities."""

    raw_slots = _require_sequence(slots, "slots")
    enabled_slots: list[Mapping[str, object]] = []
    for index, raw_value in enumerate(raw_slots):
        slot = _require_mapping(raw_value, f"slots[{index}]")
        enabled = slot.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"slots[{index}].enabled must be boolean")
        if enabled:
            enabled_slots.append(slot)

    enabled_slots.sort(
        key=lambda slot: _require_positive_int(slot.get("slot_no"), "slot_no")
    )
    seen_slot_numbers: set[int] = set()
    references: list[dict[str, object]] = []
    media: list[dict[str, object]] = []
    for position, slot in enumerate(enabled_slots, start=1):
        slot_no = _require_positive_int(slot.get("slot_no"), "slot_no")
        if slot_no > 9:
            raise ValueError("slot_no must be between 1 and 9")
        if slot_no in seen_slot_numbers:
            raise ValueError(f"slot_no {slot_no} must be unique")
        seen_slot_numbers.add(slot_no)

        asset_id_value = slot.get("asset_id")
        if asset_id_value is None:
            asset_type = _require_text(
                slot.get("asset_type_snapshot"),
                f"slot {slot_no}.asset_type_snapshot",
            )
            if asset_type not in _REFERENCE_TYPES:
                raise ValueError(
                    f"slot {slot_no}.asset_type_snapshot must be character or scene"
                )
            asset_name = _require_text(
                slot.get("asset_name_snapshot"),
                f"slot {slot_no}.asset_name_snapshot",
            )
            asset_description: str | None = None
            asset_revision: int | None = None
        else:
            asset_id = _require_positive_int(
                asset_id_value, f"slot {slot_no}.asset_id"
            )
            asset_type, asset_name, asset_description, asset_revision = (
                _asset_snapshot(
                    slot.get("asset"),
                    field=f"slot {slot_no}.asset",
                    expected_id=asset_id,
                )
            )

        del asset_revision
        override_path = slot.get("override_image_path")
        override_digest = slot.get("override_sha256")
        if (override_path is None) != (override_digest is None):
            raise ValueError(
                f"slot {slot_no} override path and hash must be provided together"
            )

        reference_name = f"subject{position}"
        if override_path is not None:
            media_item = _reference_media(
                path=override_path,
                digest=override_digest,
                field=f"slot {slot_no}.override",
            )
            image_source = "override"
            image_id: int | None = None
            reference_override_digest = media_item["sha256"]
        else:
            if asset_id_value is None:
                raise ValueError(
                    f"R10 slot {slot_no} has a deleted asset without an override"
                )
            current_image = _require_mapping(
                slot.get("current_image"), f"slot {slot_no}.current_image"
            )
            image_id = _require_positive_int(
                current_image.get("id"), f"slot {slot_no}.current_image.id"
            )
            media_item = _reference_media(
                path=current_image.get("file_path"),
                digest=current_image.get("sha256"),
                field=f"slot {slot_no}.current_image",
            )
            image_source = "asset_current"
            reference_override_digest = None

        references.append(
            {
                "slot_no": slot_no,
                "reference_name": reference_name,
                "asset_type": asset_type,
                "asset_name": asset_name,
                "asset_description": asset_description,
                "image_source": image_source,
                "image_id": image_id,
                "override_sha256": reference_override_digest,
            }
        )
        media.append(media_item)

    return ClipVideoReferences(
        references=tuple(references),
        reference_media=tuple(media),
    )


def project_clip_video_references(
    references: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Project reference identities to the six fields exposed in the prompt."""

    raw_references = _require_sequence(references, "references")
    projected: list[dict[str, object]] = []
    for index, value in enumerate(raw_references):
        reference = _require_mapping(value, f"references[{index}]")
        if set(reference) != set(_REFERENCE_FIELDS):
            raise ValueError(f"references[{index}] has invalid identity fields")
        projected.append(
            {field: copy.deepcopy(reference[field]) for field in _REFERENCE_PROMPT_FIELDS}
        )
    return tuple(projected)


def _workflow_input_location(
    workflow: Mapping[str, object], path: object, field: str
) -> tuple[dict[str, object], str]:
    if not isinstance(path, str):
        raise ValueError(f"{field} must be a text path")
    segments = path.split(".")
    if (
        len(segments) < 3
        or not segments[0].isdigit()
        or segments[1] != "inputs"
        or any(
            not segment
            or any(character in segment for character in _C009_PATH_FORBIDDEN)
            for segment in segments
        )
    ):
        raise ValueError(f"{field} must use an exact workflow input path")
    node = workflow.get(segments[0])
    if not isinstance(node, dict):
        raise ValueError(f"{field} node does not exist")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"{field} node inputs must be an object")
    input_key = ".".join(segments[2:])
    if input_key not in inputs:
        raise ValueError(f"{field} does not exist")
    return inputs, input_key


def _workflow_node(
    workflow: Mapping[str, object], node_id: str, field: str
) -> dict[str, object]:
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ValueError(f"{field} node does not exist")
    return node


def _validate_minimax_binding_for_injection(
    workflow: dict[str, object],
    *,
    prompt_path: object,
    seed_path: object,
    duration_path: object,
    ref_image_paths: object,
    ref_consumer_paths: object,
) -> tuple[tuple[str, ...], tuple[tuple[dict[str, object], str], ...]]:
    prompt_inputs, prompt_key = _workflow_input_location(
        workflow, prompt_path, "prompt_path"
    )
    if not isinstance(prompt_inputs[prompt_key], str):
        raise ValueError("prompt_path leaf must be a string")
    seed_inputs, seed_key = _workflow_input_location(
        workflow, seed_path, "seed_path"
    )
    if isinstance(seed_inputs[seed_key], bool) or not isinstance(
        seed_inputs[seed_key], int
    ):
        raise ValueError("seed_path leaf must be an integer")
    duration_inputs, duration_key = _workflow_input_location(
        workflow, duration_path, "duration_path"
    )
    duration_value = duration_inputs[duration_key]
    if isinstance(duration_value, bool) or not isinstance(
        duration_value, (int, float)
    ) or not math.isfinite(float(duration_value)):
        raise ValueError("duration_path leaf must be a finite number")

    image_paths = _require_sequence(ref_image_paths, "ref_image_paths")
    consumer_paths = _require_sequence(
        ref_consumer_paths, "ref_consumer_paths"
    )
    if len(image_paths) != _C009_REFERENCE_COUNT:
        raise ValueError("ref_image_paths must contain exactly 9 paths")
    if len(consumer_paths) != _C009_REFERENCE_COUNT:
        raise ValueError("ref_consumer_paths must contain exactly 9 paths")

    image_node_ids: list[str] = []
    consumer_locations: list[tuple[dict[str, object], str]] = []
    for index, (image_path, consumer_path) in enumerate(
        zip(image_paths, consumer_paths, strict=True)
    ):
        image_segments = image_path.split(".") if isinstance(image_path, str) else []
        image_inputs, image_key = _workflow_input_location(
            workflow, image_path, f"ref_image_paths[{index}]"
        )
        image_node_id = image_segments[0]
        image_node = _workflow_node(
            workflow, image_node_id, f"ref_image_paths[{index}]"
        )
        if image_key != "image" or image_node.get("class_type") != "LoadImage":
            raise ValueError(
                f"ref_image_paths[{index}] must reference a LoadImage image input"
            )
        expected_sentinel = f"__C009_REFERENCE_{index + 1:02d}__.png"
        if image_inputs[image_key] != expected_sentinel:
            raise ValueError(
                f"ref_image_paths[{index}] contains a preset instead of the C009 sentinel"
            )
        if image_node_id in image_node_ids:
            raise ValueError("reference image nodes must be unique")
        image_node_ids.append(image_node_id)

        consumer_segments = (
            consumer_path.split(".")
            if isinstance(consumer_path, str)
            else []
        )
        consumer_inputs, consumer_key = _workflow_input_location(
            workflow, consumer_path, f"ref_consumer_paths[{index}]"
        )
        consumer_node = _workflow_node(
            workflow,
            consumer_segments[0],
            f"ref_consumer_paths[{index}]",
        )
        expected_consumer_key = f"ref_images.ref_image_{index}"
        if (
            consumer_key != expected_consumer_key
            or consumer_node.get("class_type") != "MiniMaxH3ReferenceToVideo"
        ):
            raise ValueError(
                f"ref_consumer_paths[{index}] must reference the H3 consumer input"
            )
        link = consumer_inputs[consumer_key]
        if (
            not isinstance(link, list)
            or len(link) != 2
            or link[0] != image_node_id
            or isinstance(link[1], bool)
            or link[1] != 0
        ):
            raise ValueError(
                f"ref_consumer_paths[{index}] is not linked to its image node"
            )
        consumer_locations.append((consumer_inputs, consumer_key))

    return tuple(image_node_ids), tuple(consumer_locations)


def _validate_no_removed_workflow_references(
    value: object, removed_node_ids: frozenset[str], field: str
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_no_removed_workflow_references(
                item, removed_node_ids, f"{field}.{key}"
            )
        return
    if isinstance(value, (list, tuple)):
        if (
            len(value) == 2
            and value[0] in removed_node_ids
            and isinstance(value[1], int)
            and not isinstance(value[1], bool)
        ):
            raise ValueError(f"{field} contains an orphaned reference")
        for index, item in enumerate(value):
            _validate_no_removed_workflow_references(
                item, removed_node_ids, f"{field}[{index}]"
            )
        return
    if isinstance(value, str) and "__C009_REFERENCE_" in value:
        raise ValueError(f"{field} contains a C009 reference sentinel")


def inject_minimaxh3_workflow_inputs(
    workflow: Mapping[str, object],
    *,
    prompt_path: str,
    seed_path: str,
    duration_path: str,
    ref_image_paths: Sequence[str],
    ref_consumer_paths: Sequence[str],
    built_prompt: str,
    seed: int,
    requested_duration: int,
    upload_paths: Sequence[str],
) -> dict[str, object]:
    """Deep-copy a validated binding and inject the selected references."""

    if not isinstance(workflow, Mapping):
        raise ValueError("workflow must be an object")
    if not isinstance(built_prompt, str) or not built_prompt.strip():
        raise ValueError("built_prompt must be non-empty text")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _SEED_MASK:
        raise ValueError("seed must be a 63-bit integer")
    if (
        isinstance(requested_duration, bool)
        or not isinstance(requested_duration, int)
        or requested_duration <= 0
    ):
        raise ValueError("requested_duration must be a positive integer")

    copied = copy.deepcopy(dict(workflow))
    image_node_ids, consumer_locations = _validate_minimax_binding_for_injection(
        copied,
        prompt_path=prompt_path,
        seed_path=seed_path,
        duration_path=duration_path,
        ref_image_paths=ref_image_paths,
        ref_consumer_paths=ref_consumer_paths,
    )
    paths = _require_sequence(upload_paths, "upload_paths")
    if not 1 <= len(paths) <= _C009_REFERENCE_COUNT:
        raise ValueError("upload_paths must contain between 1 and 9 paths")
    safe_paths: list[str] = []
    for index, path in enumerate(paths):
        safe_path, _ = _safe_image_path(path, f"upload_paths[{index}]")
        if "__C009_REFERENCE_" in safe_path:
            raise ValueError("upload_paths must not contain a C009 sentinel")
        if safe_path in safe_paths:
            raise ValueError("upload_paths must be unique")
        safe_paths.append(safe_path)

    prompt_inputs, prompt_key = _workflow_input_location(
        copied, prompt_path, "prompt_path"
    )
    seed_inputs, seed_key = _workflow_input_location(copied, seed_path, "seed_path")
    duration_inputs, duration_key = _workflow_input_location(
        copied, duration_path, "duration_path"
    )
    prompt_inputs[prompt_key] = built_prompt
    seed_inputs[seed_key] = seed
    duration_inputs[duration_key] = requested_duration

    kept_node_ids = set(image_node_ids[: len(safe_paths)])
    for index, path in enumerate(safe_paths):
        image_inputs, image_key = _workflow_input_location(
            copied, ref_image_paths[index], f"ref_image_paths[{index}]"
        )
        image_inputs[image_key] = path

    removed_node_ids = frozenset(image_node_ids[len(safe_paths) :])
    for index in range(len(safe_paths), _C009_REFERENCE_COUNT):
        image_node_id = image_node_ids[index]
        del copied[image_node_id]
        consumer_inputs, consumer_key = consumer_locations[index]
        del consumer_inputs[consumer_key]

    _validate_no_removed_workflow_references(copied, removed_node_ids, "workflow")
    load_image_ids = {
        node_id
        for node_id, node in copied.items()
        if isinstance(node, Mapping) and node.get("class_type") == "LoadImage"
    }
    if load_image_ids != kept_node_ids:
        raise ValueError("workflow contains a preset or orphaned LoadImage node")
    for index in range(len(safe_paths)):
        image_inputs, image_key = _workflow_input_location(
            copied, ref_image_paths[index], f"ref_image_paths[{index}]"
        )
        if image_inputs[image_key] != safe_paths[index]:
            raise ValueError("workflow reference image path was not injected")
        consumer_inputs, consumer_key = _workflow_input_location(
            copied, ref_consumer_paths[index], f"ref_consumer_paths[{index}]"
        )
        if consumer_inputs[consumer_key] != [image_node_ids[index], 0]:
            raise ValueError("workflow reference consumer is orphaned")
    _validate_no_removed_workflow_references(copied, frozenset(), "workflow")
    return copied


def _compact_json(value: object, field: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain finite JSON values") from exc


def _render_template(
    template_content: str, values: Mapping[str, str]
) -> str:
    if not isinstance(template_content, str):
        raise ValueError("minimaxh3 template content must be text")
    matches = list(_PLACEHOLDER_PATTERN.finditer(template_content))
    names = [match.group(1) for match in matches]
    unmatched = _PLACEHOLDER_PATTERN.sub("", template_content)
    if (
        set(names) != _REQUIRED_PLACEHOLDERS
        or "{{" in unmatched
        or "}}" in unmatched
    ):
        raise ValueError(
            "minimaxh3 template must contain exactly the required placeholders"
        )
    return _PLACEHOLDER_PATTERN.sub(
        lambda match: values[match.group(1)], template_content
    )


def render_minimaxh3_prompt(
    template_content: str,
    *,
    shots: Sequence[Mapping[str, object]],
    references: Sequence[Mapping[str, object]],
    style: str,
    requested_duration: int,
    user_note: str | None,
) -> str:
    """Render the exact five-variable MiniMax H3 user prompt."""

    if not isinstance(style, str):
        raise ValueError("minimaxh3 style must be text")
    if isinstance(requested_duration, bool) or not isinstance(
        requested_duration, int
    ) or requested_duration <= 0:
        raise ValueError("minimaxh3 requested_duration must be a positive integer")
    if user_note is not None and not isinstance(user_note, str):
        raise ValueError("minimaxh3 user_note must be text or null")
    shot_values = project_clip_video_shots(shots)
    reference_values = project_clip_video_references(references)
    return _render_template(
        template_content,
        {
            "shots": _compact_json(shot_values, "shots"),
            "references": _compact_json(reference_values, "references"),
            "style": style,
            "requested_duration": str(requested_duration),
            "user_note": "" if user_note is None else user_note,
        },
    )


def build_minimaxh3_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "minimaxh3",
            "strict": True,
            "schema": copy.deepcopy(MINIMAXH3_SCHEMA),
        },
    }


def validate_minimaxh3_response(response: Mapping[str, object]) -> str:
    if not isinstance(response, Mapping) or set(response) != {"prompt"}:
        raise ValueError("minimaxh3 response must contain only prompt")
    prompt = response["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("minimaxh3 response prompt must be non-empty")
    return prompt


def _normalize_hash_shots(
    shots: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    raw_shots = _require_sequence(shots, "shots")
    return [
        _shot_snapshot(value, f"shots[{index}]")
        for index, value in enumerate(raw_shots)
    ]


def _normalize_hash_references(
    references: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    raw_references = _require_sequence(references, "references")
    normalized: list[dict[str, object]] = []
    for index, value in enumerate(raw_references):
        reference = _require_mapping(value, f"references[{index}]")
        if set(reference) != set(_REFERENCE_FIELDS):
            raise ValueError(f"references[{index}] has invalid identity fields")
        normalized.append(
            {
                field: copy.deepcopy(reference[field])
                for field in _REFERENCE_FIELDS
            }
        )
    return normalized


def serialize_clip_video_input(
    *,
    shots: Sequence[Mapping[str, object]],
    references: Sequence[Mapping[str, object]],
    style_prompt_fragment: str,
    template_content: str,
    user_note: str | None,
    requested_duration: int,
    model: str,
    workflow_hash: str,
) -> bytes:
    """Serialize the exact eight R4 members as compact UTF-8 JSON bytes."""

    if not isinstance(style_prompt_fragment, str):
        raise ValueError("style_prompt_fragment must be text")
    if not isinstance(template_content, str):
        raise ValueError("template_content must be text")
    if user_note is not None and not isinstance(user_note, str):
        raise ValueError("user_note must be text or null")
    if isinstance(requested_duration, bool) or not isinstance(
        requested_duration, int
    ) or requested_duration <= 0:
        raise ValueError("requested_duration must be a positive integer")
    if not isinstance(model, str) or not model:
        raise ValueError("model must be non-empty text")
    _require_sha256(workflow_hash, "workflow_hash")
    values = [
        _normalize_hash_shots(shots),
        _normalize_hash_references(references),
        style_prompt_fragment,
        template_content,
        user_note,
        requested_duration,
        model,
        workflow_hash,
    ]
    return _compact_json(values, "clip video input").encode("utf-8")


def build_clip_video_input_hash(
    *,
    shots: Sequence[Mapping[str, object]],
    references: Sequence[Mapping[str, object]],
    style_prompt_fragment: str,
    template_content: str,
    user_note: str | None,
    requested_duration: int,
    model: str,
    workflow_hash: str,
) -> str:
    return hashlib.sha256(
        serialize_clip_video_input(
            shots=shots,
            references=references,
            style_prompt_fragment=style_prompt_fragment,
            template_content=template_content,
            user_note=user_note,
            requested_duration=requested_duration,
            model=model,
            workflow_hash=workflow_hash,
        )
    ).hexdigest()


def build_clip_video_identifiers(
    request_id: str | None,
) -> ClipVideoIdentifiers:
    normalized_request_id = normalize_request_id(request_id)
    if normalized_request_id is None:
        return ClipVideoIdentifiers(
            seed=secrets.randbelow(1 << 63),
            comfy_prompt_id=str(uuid4()),
        )
    prompt_uuid = uuid5(GEN_CLIP_VIDEO_NAMESPACE, normalized_request_id)
    return ClipVideoIdentifiers(
        seed=prompt_uuid.int & _SEED_MASK,
        comfy_prompt_id=str(prompt_uuid),
    )
