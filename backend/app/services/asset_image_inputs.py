from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from app.tasks.queue import normalize_request_id


GEN_ASSET_IMAGE_NAMESPACE = UUID("27e66eeb-4d70-597c-8f24-fb984fab13c3")
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
_REQUIRED_PLACEHOLDERS = frozenset({"asset", "style", "user_note"})
_PATH_FORBIDDEN = frozenset("*[]|?")
_SEED_MASK = 0x7FFF_FFFF_FFFF_FFFF


ZIMAGE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class AssetImageIdentifiers:
    seed: int
    comfy_prompt_id: str


def _asset_prompt_value(asset: Mapping[str, object]) -> str:
    fields = ("type", "name", "description")
    values: dict[str, str] = {}
    for field in fields:
        value = asset.get(field)
        if not isinstance(value, str):
            raise ValueError(f"zimage asset {field} must be a string")
        values[field] = value
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def render_zimage_prompt(
    template_content: str,
    *,
    asset: Mapping[str, object],
    style: str,
    user_note: str | None,
) -> str:
    if not isinstance(template_content, str):
        raise ValueError("zimage template content must be a string")
    if not isinstance(asset, Mapping):
        raise ValueError("zimage asset must be an object")
    if not isinstance(style, str):
        raise ValueError("zimage style must be a string")
    if user_note is not None and not isinstance(user_note, str):
        raise ValueError("zimage user_note must be a string or null")

    values = {
        "asset": _asset_prompt_value(asset),
        "style": style,
        "user_note": "" if user_note is None else user_note,
    }
    matches = list(_PLACEHOLDER_PATTERN.finditer(template_content))
    names = [match.group(1) for match in matches]
    unmatched = _PLACEHOLDER_PATTERN.sub("", template_content)
    if (
        set(names) != _REQUIRED_PLACEHOLDERS
        or "{{" in unmatched
        or "}}" in unmatched
    ):
        raise ValueError(
            "zimage template must contain exactly the placeholders "
            "{{asset}}, {{style}}, and {{user_note}}"
        )
    return _PLACEHOLDER_PATTERN.sub(
        lambda match: values[match.group(1)], template_content
    )


def build_zimage_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "zimage",
            "strict": True,
            "schema": copy.deepcopy(ZIMAGE_SCHEMA),
        },
    }


def validate_zimage_response(response: Mapping[str, object]) -> str:
    if not isinstance(response, Mapping) or set(response) != {"prompt"}:
        raise ValueError("zimage response must contain only prompt")
    prompt = response["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("zimage response prompt must be non-empty")
    return prompt


def serialize_asset_image_input(
    *,
    asset_name: str,
    asset_description: str,
    asset_revision: int,
    style_prompt_fragment: str,
    template_content: str,
    user_note: str | None,
    model: str,
    workflow_hash: str,
) -> bytes:
    values = [
        asset_name,
        asset_description,
        asset_revision,
        style_prompt_fragment,
        template_content,
        user_note,
        model,
        workflow_hash,
    ]
    return json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_asset_image_input_hash(
    *,
    asset_name: str,
    asset_description: str,
    asset_revision: int,
    style_prompt_fragment: str,
    template_content: str,
    user_note: str | None,
    model: str,
    workflow_hash: str,
) -> str:
    return hashlib.sha256(
        serialize_asset_image_input(
            asset_name=asset_name,
            asset_description=asset_description,
            asset_revision=asset_revision,
            style_prompt_fragment=style_prompt_fragment,
            template_content=template_content,
            user_note=user_note,
            model=model,
            workflow_hash=workflow_hash,
        )
    ).hexdigest()


def _replace_workflow_path(
    workflow: dict[str, object], path: str, value: object
) -> None:
    segments = path.split(".")
    if any(
        not segment or any(character in segment for character in _PATH_FORBIDDEN)
        for segment in segments
    ):
        raise ValueError("workflow paths must use exact dot-separated object keys")

    current: object = workflow
    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            raise ValueError(f"workflow path does not exist: {path}")
        current = current[segment]
    if not isinstance(current, dict) or segments[-1] not in current:
        raise ValueError(f"workflow path does not exist: {path}")
    current[segments[-1]] = value


def inject_zimage_workflow_inputs(
    workflow: Mapping[str, object],
    *,
    prompt_path: str,
    seed_path: str,
    built_prompt: str,
    seed: int,
) -> dict[str, object]:
    if not isinstance(workflow, Mapping):
        raise ValueError("workflow must be an object")
    copied = copy.deepcopy(dict(workflow))
    _replace_workflow_path(copied, prompt_path, built_prompt)
    _replace_workflow_path(copied, seed_path, seed)
    return copied


def build_asset_image_identifiers(
    request_id: str | None,
) -> AssetImageIdentifiers:
    normalized_request_id = normalize_request_id(request_id)
    if normalized_request_id is None:
        return AssetImageIdentifiers(
            seed=secrets.randbelow(1 << 63),
            comfy_prompt_id=str(uuid4()),
        )

    prompt_uuid = uuid5(GEN_ASSET_IMAGE_NAMESPACE, normalized_request_id)
    return AssetImageIdentifiers(
        seed=prompt_uuid.int & _SEED_MASK,
        comfy_prompt_id=str(prompt_uuid),
    )
