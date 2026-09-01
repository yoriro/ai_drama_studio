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
