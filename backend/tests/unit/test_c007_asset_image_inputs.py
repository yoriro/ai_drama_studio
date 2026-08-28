import copy
import uuid

import pytest

from app.services.asset_image_inputs import (
    GEN_ASSET_IMAGE_NAMESPACE,
    ZIMAGE_SCHEMA,
    build_asset_image_identifiers,
    build_asset_image_input_hash,
    build_zimage_response_format,
    inject_zimage_workflow_inputs,
    render_zimage_prompt,
    serialize_asset_image_input,
    validate_zimage_response,
)
from app.tasks.queue import TaskValidationError


def test_render_zimage_prompt_uses_exact_fields_and_one_pass_substitution() -> None:
    rendered = render_zimage_prompt(
        "asset={{asset}}|style={{style}}|note={{user_note}}",
        asset={
            "id": 21,
            "type": "character",
            "name": "名字 {{style}}",
            "description": "描述",
            "revision": 3,
        },
        style="写实 {{asset}}",
        user_note="备注 {{user_note}}",
    )

    assert rendered == (
        'asset={"type":"character","name":"名字 {{style}}",'
        '"description":"描述"}|style=写实 {{asset}}|'
        "note=备注 {{user_note}}"
    )


@pytest.mark.parametrize(
    "template",
    [
        "asset={{asset}}|style={{style}}",
        "asset={{asset}}|style={{style}}|note={{user_note}}|x={{other}}",
        "asset={{asset}}|style={{style}}|note={{user_note}}|x={{",
    ],
)
def test_render_zimage_prompt_rejects_missing_unknown_or_unclosed_placeholders(
    template: str,
) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        render_zimage_prompt(
            template,
            asset={"type": "scene", "name": "场景", "description": "描述"},
            style="风格",
            user_note=None,
        )


def test_zimage_response_format_and_prompt_validation_are_closed() -> None:
    assert build_zimage_response_format() == {
        "type": "json_schema",
        "json_schema": {
            "name": "zimage",
            "strict": True,
            "schema": ZIMAGE_SCHEMA,
        },
    }
    assert validate_zimage_response({"prompt": "  image prompt  "}) == (
        "  image prompt  "
    )
    for invalid in (
        {},
        {"prompt": "prompt", "extra": False},
        {"prompt": ""},
        {"prompt": " \t"},
        {"prompt": 3},
    ):
        with pytest.raises(ValueError, match="prompt"):
            validate_zimage_response(invalid)


def test_asset_image_input_serialization_and_hash_use_fixed_eight_values() -> None:
    serialized = serialize_asset_image_input(
        asset_name="林夏",
        asset_description="蓝外套",
        asset_revision=3,
        style_prompt_fragment="写实",
        template_content="asset={{asset}}",
        user_note=None,
        model="model",
        workflow_hash="a" * 64,
    )
    assert serialized == (
        '["林夏","蓝外套",3,"写实","asset={{asset}}",null,"model",'
        '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]'
    ).encode("utf-8")
    assert build_asset_image_input_hash(
        asset_name="林夏",
        asset_description="蓝外套",
        asset_revision=3,
        style_prompt_fragment="写实",
        template_content="asset={{asset}}",
        user_note=None,
        model="model",
        workflow_hash="a" * 64,
    ) == "0257832a99810153715a0c4064b1d992b1ff7aa8b1f934db9843f65f943effe5"


@pytest.mark.parametrize(
    "field",
    [
        "asset_name",
        "asset_description",
        "asset_revision",
        "style_prompt_fragment",
        "template_content",
        "user_note",
        "model",
        "workflow_hash",
    ],
)
def test_each_r4_input_member_changes_hash(field: str) -> None:
    values: dict[str, object] = {
        "asset_name": "name",
        "asset_description": "description",
        "asset_revision": 1,
        "style_prompt_fragment": "style",
        "template_content": "template",
        "user_note": None,
        "model": "model",
        "workflow_hash": "a" * 64,
    }
    changed = dict(values)
    changed[field] = (
        2
        if field == "asset_revision"
        else "changed"
    )
    assert build_asset_image_input_hash(**values) != build_asset_image_input_hash(
        **changed
    )


def test_inject_zimage_workflow_inputs_deep_copies_and_changes_only_two_leaves() -> None:
    workflow = {
        "3": {"inputs": {"seed": 123, "other": "keep"}},
        "6": {"inputs": {"text": "old", "other": [1, 2]}},
        "9": {"class_type": "SaveImage"},
    }
    original = copy.deepcopy(workflow)

    injected = inject_zimage_workflow_inputs(
        workflow,
        prompt_path="6.inputs.text",
        seed_path="3.inputs.seed",
        built_prompt="new",
        seed=987,
    )

    assert workflow == original
    assert injected["6"]["inputs"]["text"] == "new"
    assert injected["3"]["inputs"]["seed"] == 987
    assert injected["6"]["inputs"]["other"] == [1, 2]
    assert injected["3"]["inputs"]["other"] == "keep"
    assert injected is not workflow

    with pytest.raises(ValueError, match="does not exist"):
        inject_zimage_workflow_inputs(
            workflow,
            prompt_path="6.inputs.missing",
            seed_path="3.inputs.seed",
            built_prompt="new",
            seed=987,
        )


def test_asset_image_identifiers_follow_random_and_frozen_uuid5_contract() -> None:
    first = build_asset_image_identifiers(None)
    second = build_asset_image_identifiers(None)
    assert 0 <= first.seed <= 2**63 - 1
    assert 0 <= second.seed <= 2**63 - 1
    assert uuid.UUID(first.comfy_prompt_id).version == 4
    assert uuid.UUID(second.comfy_prompt_id).version == 4
    assert (first.seed, first.comfy_prompt_id) != (
        second.seed,
        second.comfy_prompt_id,
    )

    fixed = build_asset_image_identifiers(" abc ")
    assert fixed.comfy_prompt_id == "f0faf273-5fe9-5726-98be-3d449efdbe8d"
    assert fixed.seed == 1782929867419795085
    assert uuid.UUID(fixed.comfy_prompt_id).version == 5
    assert GEN_ASSET_IMAGE_NAMESPACE == uuid.UUID(
        "27e66eeb-4d70-597c-8f24-fb984fab13c3"
    )


def test_asset_image_identifier_preserves_case_spaces_and_unicode_codepoints() -> None:
    assert build_asset_image_identifiers("abc") != build_asset_image_identifiers(
        "ABC"
    )
    assert build_asset_image_identifiers("a b") != build_asset_image_identifiers(
        "ab"
    )
    assert build_asset_image_identifiers("é") != build_asset_image_identifiers(
        "e\u0301"
    )

    with pytest.raises(TaskValidationError):
        build_asset_image_identifiers("   ")
