from __future__ import annotations

import copy
import json
import uuid

import pytest

from app.services import clip_video_inputs
from app.services.clip_video_inputs import (
    GEN_CLIP_VIDEO_NAMESPACE,
    MINIMAXH3_SCHEMA,
    build_clip_video_identifiers,
    build_clip_video_input_hash,
    build_clip_video_references,
    build_clip_video_shot_snapshots,
    build_minimaxh3_response_format,
    project_clip_video_references,
    project_clip_video_shots,
    render_minimaxh3_prompt,
    serialize_clip_video_input,
    validate_minimaxh3_response,
)


WORKFLOW_HASH = "a" * 64


def _raw_shot(
    *,
    position: int,
    shot_id: int,
    order_index: int,
    revision: int = 1,
    description: str = "镜头描述",
) -> dict[str, object]:
    return {
        "position": position,
        "id": shot_id,
        "order": order_index,
        "duration_est": 2.5,
        "shot_type": "medium",
        "camera": "static",
        "description": description,
        "dialogue": "台词",
        "revision": revision,
        "asset_ids": [7, 3],
    }


def _full_shots() -> tuple[dict[str, object], ...]:
    return build_clip_video_shot_snapshots(
        [
            _raw_shot(position=2, shot_id=12, order_index=2),
            _raw_shot(position=1, shot_id=11, order_index=1),
        ]
    )


def _slots() -> list[dict[str, object]]:
    return [
        {
            "slot_no": 3,
            "enabled": True,
            "asset_id": 20,
            "asset_name_snapshot": "旧名",
            "asset_type_snapshot": "character",
            "asset": {
                "id": 20,
                "type": "character",
                "name": "当前人物",
                "description": "当前人物描述",
                "revision": 4,
            },
            "current_image": {
                "id": 203,
                "file_path": "projects/1/assets/20/203.webp",
                "sha256": "b" * 64,
            },
            "override_image_path": "projects/1/clips/2/slots/3.png",
            "override_sha256": "c" * 64,
        },
        {
            "slot_no": 1,
            "enabled": True,
            "asset_id": 10,
            "asset_name_snapshot": "快照人物",
            "asset_type_snapshot": "character",
            "asset": {
                "id": 10,
                "type": "character",
                "name": "活人物",
                "description": "活人物描述",
                "revision": 2,
            },
            "current_image": {
                "id": 101,
                "file_path": "projects/1/assets/10/101.png",
                "sha256": "d" * 64,
            },
            "override_image_path": None,
            "override_sha256": None,
        },
        {
            "slot_no": 5,
            "enabled": True,
            "asset_id": None,
            "asset_name_snapshot": "已删场景",
            "asset_type_snapshot": "scene",
            "asset": None,
            "current_image": None,
            "override_image_path": "projects/1/clips/2/slots/5.jpg",
            "override_sha256": "e" * 64,
        },
        {
            "slot_no": 2,
            "enabled": False,
        },
    ]


def test_shots_and_references_use_exact_snapshots_and_compact_projection() -> None:
    shots = _full_shots()
    assert shots == (
        {
            "id": 11,
            "order": 1,
            "duration_est": 2.5,
            "shot_type": "medium",
            "camera": "static",
            "description": "镜头描述",
            "dialogue": "台词",
            "revision": 1,
            "asset_ids": [3, 7],
        },
        {
            "id": 12,
            "order": 2,
            "duration_est": 2.5,
            "shot_type": "medium",
            "camera": "static",
            "description": "镜头描述",
            "dialogue": "台词",
            "revision": 1,
            "asset_ids": [3, 7],
        },
    )
    assert project_clip_video_shots(shots) == (
        {
            "order": 1,
            "duration_est": 2.5,
            "shot_type": "medium",
            "camera": "static",
            "description": "镜头描述",
            "dialogue": "台词",
        },
        {
            "order": 2,
            "duration_est": 2.5,
            "shot_type": "medium",
            "camera": "static",
            "description": "镜头描述",
            "dialogue": "台词",
        },
    )

    references = build_clip_video_references(_slots())
    assert references.references == (
        {
            "slot_no": 1,
            "reference_name": "subject1",
            "asset_type": "character",
            "asset_name": "活人物",
            "asset_description": "活人物描述",
            "image_source": "asset_current",
            "image_id": 101,
            "override_sha256": None,
        },
        {
            "slot_no": 3,
            "reference_name": "subject2",
            "asset_type": "character",
            "asset_name": "当前人物",
            "asset_description": "当前人物描述",
            "image_source": "override",
            "image_id": None,
            "override_sha256": "c" * 64,
        },
        {
            "slot_no": 5,
            "reference_name": "subject3",
            "asset_type": "scene",
            "asset_name": "已删场景",
            "asset_description": None,
            "image_source": "override",
            "image_id": None,
            "override_sha256": "e" * 64,
        },
    )
    assert references.reference_media == (
        {
            "file_path": "projects/1/assets/10/101.png",
            "extension": "png",
            "sha256": "d" * 64,
        },
        {
            "file_path": "projects/1/clips/2/slots/3.png",
            "extension": "png",
            "sha256": "c" * 64,
        },
        {
            "file_path": "projects/1/clips/2/slots/5.jpg",
            "extension": "jpg",
            "sha256": "e" * 64,
        },
    )
    assert project_clip_video_references(references.references) == (
        {
            "slot_no": 1,
            "reference_name": "subject1",
            "asset_type": "character",
            "asset_name": "活人物",
            "asset_description": "活人物描述",
            "image_source": "asset_current",
        },
        {
            "slot_no": 3,
            "reference_name": "subject2",
            "asset_type": "character",
            "asset_name": "当前人物",
            "asset_description": "当前人物描述",
            "image_source": "override",
        },
        {
            "slot_no": 5,
            "reference_name": "subject3",
            "asset_type": "scene",
            "asset_name": "已删场景",
            "asset_description": None,
            "image_source": "override",
        },
    )


def test_deleted_slot_without_override_is_r10_and_live_asset_values_win() -> None:
    broken = copy.deepcopy(_slots())
    deleted = next(item for item in broken if item["slot_no"] == 5)
    deleted["override_image_path"] = None
    deleted["override_sha256"] = None
    with pytest.raises(ValueError, match=r"R10 slot 5"):
        build_clip_video_references(broken)

    live = copy.deepcopy(_slots())
    live_asset = next(item for item in live if item["slot_no"] == 1)["asset"]
    assert isinstance(live_asset, dict)
    live_asset["name"] = "后来的人物"
    live_asset["description"] = "后来的人物描述"
    result = build_clip_video_references(live)
    assert result.references[0]["asset_name"] == "后来的人物"
    assert result.references[0]["asset_description"] == "后来的人物描述"


def test_minimax_prompt_is_compact_and_exposes_only_six_reference_fields() -> None:
    references = build_clip_video_references(_slots()).references
    rendered = render_minimaxh3_prompt(
        "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note={{user_note}}",
        shots=_full_shots(),
        references=references,
        style="写实",
        requested_duration=5,
        user_note="  保留原构图  ",
    )
    assert rendered == (
        'S=[{"order":1,"duration_est":2.5,"shot_type":"medium",'
        '"camera":"static","description":"镜头描述","dialogue":"台词"},'
        '{"order":2,"duration_est":2.5,"shot_type":"medium",'
        '"camera":"static","description":"镜头描述","dialogue":"台词"}]|'
        'R=[{"slot_no":1,"reference_name":"subject1","asset_type":"character",'
        '"asset_name":"活人物","asset_description":"活人物描述",'
        '"image_source":"asset_current"},{"slot_no":3,'
        '"reference_name":"subject2","asset_type":"character",'
        '"asset_name":"当前人物","asset_description":"当前人物描述",'
        '"image_source":"override"},{"slot_no":5,'
        '"reference_name":"subject3","asset_type":"scene",'
        '"asset_name":"已删场景","asset_description":null,'
        '"image_source":"override"}]|style=写实|duration=5|note=  保留原构图  '
    )
    assert "image_id" not in rendered
    assert "override_sha256" not in rendered


@pytest.mark.parametrize(
    "template",
    [
        "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}",
        "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note={{other}}",
        "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note={{user_note",
        "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note=}}",
    ],
)
def test_minimax_prompt_rejects_missing_unknown_and_unclosed_placeholders(
    template: str,
) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        render_minimaxh3_prompt(
            template,
            shots=_full_shots(),
            references=build_clip_video_references(_slots()).references,
            style="写实",
            requested_duration=5,
            user_note=None,
        )


def test_minimax_schema_and_response_validation_are_closed() -> None:
    assert build_minimaxh3_response_format() == {
        "type": "json_schema",
        "json_schema": {
            "name": "minimaxh3",
            "strict": True,
            "schema": MINIMAXH3_SCHEMA,
        },
    }
    assert validate_minimaxh3_response({"prompt": "  生成视频  "}) == (
        "  生成视频  "
    )
    for invalid in (
        {},
        {"prompt": "prompt", "extra": False},
        {"prompt": None},
        {"prompt": ""},
        {"prompt": " \t"},
        {"prompt": 3},
    ):
        with pytest.raises(ValueError, match="prompt"):
            validate_minimaxh3_response(invalid)


def _hash_values() -> dict[str, object]:
    return {
        "shots": _full_shots(),
        "references": build_clip_video_references(_slots()).references,
        "style_prompt_fragment": "写实风格",
        "template_content": "S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note={{user_note}}",
        "user_note": None,
        "requested_duration": 5,
        "model": "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit",
        "workflow_hash": WORKFLOW_HASH,
    }


def test_clip_video_hash_serializes_exact_eight_members() -> None:
    values = _hash_values()
    serialized = serialize_clip_video_input(**values)
    expected = (
        '[[{"id":11,"order":1,"duration_est":2.5,"shot_type":"medium",'
        '"camera":"static","description":"镜头描述","dialogue":"台词",'
        '"revision":1,"asset_ids":[3,7]},{"id":12,"order":2,'
        '"duration_est":2.5,"shot_type":"medium","camera":"static",'
        '"description":"镜头描述","dialogue":"台词","revision":1,'
        '"asset_ids":[3,7]}],[{"slot_no":1,"reference_name":"subject1",'
        '"asset_type":"character","asset_name":"活人物",'
        '"asset_description":"活人物描述","image_source":"asset_current",'
        '"image_id":101,"override_sha256":null},{"slot_no":3,'
        '"reference_name":"subject2","asset_type":"character",'
        '"asset_name":"当前人物","asset_description":"当前人物描述",'
        '"image_source":"override","image_id":null,"override_sha256":"'
        + "c" * 64
        + '"},{"slot_no":5,"reference_name":"subject3",'
        '"asset_type":"scene","asset_name":"已删场景",'
        '"asset_description":null,"image_source":"override","image_id":null,'
        '"override_sha256":"'
        + "e" * 64
        + '"}],"写实风格","S={{shots}}|R={{references}}|style={{style}}|duration={{requested_duration}}|note={{user_note}}",null,5,"Qwen3-30B-A3B-Instruct-2507-AWQ-4bit","'
        + WORKFLOW_HASH
        + '"]'
    ).encode("utf-8")
    assert serialized == expected
    assert build_clip_video_input_hash(**values) == (
        "2a87d0d8318225f80c836491a00d81c4a934c4fb426e3a4f5dfbfbce8844108e"
    )


@pytest.mark.parametrize(
    "member",
    [
        "shots",
        "references",
        "style_prompt_fragment",
        "template_content",
        "user_note",
        "requested_duration",
        "model",
        "workflow_hash",
    ],
)
def test_each_r4_member_changes_hash(member: str) -> None:
    values = _hash_values()
    changed = copy.deepcopy(values)
    if member == "shots":
        changed[member][0]["revision"] = 2  # type: ignore[index]
    elif member == "references":
        changed[member][0]["asset_name"] = "变化人物"  # type: ignore[index]
    elif member == "user_note":
        changed[member] = ""
    elif member == "requested_duration":
        changed[member] = 6
    elif member == "workflow_hash":
        changed[member] = "b" * 64
    else:
        changed[member] = f"changed-{member}"
    assert build_clip_video_input_hash(**values) != build_clip_video_input_hash(
        **changed
    )


def test_r4_restore_requires_revision_and_distinguishes_note_states() -> None:
    values = _hash_values()
    base_hash = build_clip_video_input_hash(**values)
    restored = copy.deepcopy(values)
    assert build_clip_video_input_hash(**restored) == base_hash

    text_changed = copy.deepcopy(values)
    text_changed["shots"][0]["description"] = "新文本"  # type: ignore[index]
    assert build_clip_video_input_hash(**text_changed) != base_hash
    text_restored_revision_changed = copy.deepcopy(text_changed)
    text_restored_revision_changed["shots"][0]["description"] = "镜头描述"  # type: ignore[index]
    text_restored_revision_changed["shots"][0]["revision"] = 2  # type: ignore[index]
    assert build_clip_video_input_hash(**text_restored_revision_changed) != base_hash

    for note in (None, "", " "):
        noted = copy.deepcopy(values)
        noted["user_note"] = note
        if note is not None:
            assert build_clip_video_input_hash(**noted) != base_hash
    empty = copy.deepcopy(values)
    empty["user_note"] = ""
    whitespace = copy.deepcopy(values)
    whitespace["user_note"] = " "
    assert build_clip_video_input_hash(**empty) != build_clip_video_input_hash(
        **whitespace
    )


def test_clip_video_identifiers_use_only_normalized_request_id_and_fixed_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = build_clip_video_identifiers(" abc ")
    assert fixed.comfy_prompt_id == "3088d9e1-4253-5fff-896e-87e5f5312d20"
    assert fixed.seed == 679630015510424864
    assert uuid.UUID(fixed.comfy_prompt_id).version == 5
    assert GEN_CLIP_VIDEO_NAMESPACE == uuid.UUID(
        "17c124be-f03e-5a69-b4e5-e3a63f62994b"
    )
    assert build_clip_video_identifiers("abc") == fixed
    assert build_clip_video_identifiers("ABC") != fixed
    assert build_clip_video_identifiers("a b") != build_clip_video_identifiers("ab")

    monkeypatch.setattr(clip_video_inputs.secrets, "randbelow", lambda _limit: 0)
    lower = build_clip_video_identifiers(None)
    monkeypatch.setattr(
        clip_video_inputs.secrets,
        "randbelow",
        lambda _limit: (1 << 63) - 1,
    )
    upper = build_clip_video_identifiers(None)
    assert lower.seed == 0
    assert upper.seed == (1 << 63) - 1
    assert uuid.UUID(lower.comfy_prompt_id).version == 4
    assert uuid.UUID(upper.comfy_prompt_id).version == 4
