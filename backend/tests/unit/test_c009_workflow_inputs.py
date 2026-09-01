from __future__ import annotations

import copy
import json

import pytest

from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services.clip_video_inputs import inject_minimaxh3_workflow_inputs


def _binding_definition() -> tuple[object, dict[str, object]]:
    snapshot = load_minimax_binding_snapshot()
    payload = snapshot.workflow_payload()
    definition = payload["definition"]
    assert isinstance(definition, dict)
    return snapshot, definition


def _inject(
    workflow: dict[str, object],
    snapshot: object,
    upload_paths: list[str],
) -> dict[str, object]:
    assert hasattr(snapshot, "prompt_path")
    assert hasattr(snapshot, "seed_path")
    assert hasattr(snapshot, "duration_path")
    assert hasattr(snapshot, "ref_image_paths")
    assert hasattr(snapshot, "ref_consumer_paths")
    return inject_minimaxh3_workflow_inputs(
        workflow,
        prompt_path=snapshot.prompt_path,
        seed_path=snapshot.seed_path,
        duration_path=snapshot.duration_path,
        ref_image_paths=snapshot.ref_image_paths,
        ref_consumer_paths=snapshot.ref_consumer_paths,
        built_prompt="built prompt",
        seed=679630015510424864,
        requested_duration=11,
        upload_paths=upload_paths,
    )


@pytest.mark.parametrize(
    "reference_count",
    [pytest.param(1, id="one"), pytest.param(2, id="two"), pytest.param(9, id="nine")],
)
def test_injects_and_prunes_real_minimax_workflow(
    reference_count: int,
) -> None:
    snapshot, workflow = _binding_definition()
    original = copy.deepcopy(workflow)
    upload_paths = [
        f"c009/task-42/subject{index}.png"
        for index in range(1, reference_count + 1)
    ]

    injected = _inject(workflow, snapshot, upload_paths)

    assert workflow == original
    assert injected is not workflow
    assert injected["138"]["inputs"]["value"] == "built prompt"  # type: ignore[index]
    assert injected["129"]["inputs"]["noise_seed"] == 679630015510424864  # type: ignore[index]
    assert injected["132"]["inputs"]["value"] == 11  # type: ignore[index]

    image_node_ids = [path.split(".", 1)[0] for path in snapshot.ref_image_paths]
    removed_image_node_ids = set(image_node_ids[reference_count:])
    assert set(injected) == set(original) - removed_image_node_ids
    for index, path in enumerate(upload_paths):
        image_node_id = image_node_ids[index]
        assert injected[image_node_id]["class_type"] == "LoadImage"  # type: ignore[index]
        assert injected[image_node_id]["inputs"]["image"] == path  # type: ignore[index]
        assert injected["186"]["inputs"][  # type: ignore[index]
            f"ref_images.ref_image_{index}"
        ] == [image_node_id, 0]  # type: ignore[index]

    expected_consumer_keys = {
        f"ref_images.ref_image_{index}" for index in range(reference_count)
    }
    actual_consumer_keys = {
        key
        for key in injected["186"]["inputs"]  # type: ignore[index]
        if key.startswith("ref_images.ref_image_")
    }
    assert actual_consumer_keys == expected_consumer_keys
    assert all(
        node_id not in injected for node_id in removed_image_node_ids
    )
    assert "__C009_REFERENCE_" not in json.dumps(injected, ensure_ascii=False)


@pytest.mark.parametrize(
    ("upload_paths", "message"),
    [
        ([], "between 1 and 9"),
        ([f"task/subject{index}.png" for index in range(10)], "between 1 and 9"),
        (["../subject1.png"], "safe relative path"),
        (["task/subject1.txt"], "supported image extension"),
        (["task/subject1.png", "task/subject1.png"], "unique"),
        (["__C009_REFERENCE_01__.png"], "sentinel"),
    ],
)
def test_rejects_invalid_upload_path_contracts(
    upload_paths: list[str], message: str
) -> None:
    snapshot, workflow = _binding_definition()
    with pytest.raises(ValueError, match=message):
        _inject(workflow, snapshot, upload_paths)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("built_prompt", "", "built_prompt"),
        ("seed", True, "63-bit integer"),
        ("seed", -1, "63-bit integer"),
        ("requested_duration", 0, "positive integer"),
        ("requested_duration", 11.0, "positive integer"),
    ],
)
def test_rejects_invalid_injected_values(
    field: str, value: object, message: str
) -> None:
    snapshot, workflow = _binding_definition()
    kwargs: dict[str, object] = {
        "prompt_path": snapshot.prompt_path,
        "seed_path": snapshot.seed_path,
        "duration_path": snapshot.duration_path,
        "ref_image_paths": snapshot.ref_image_paths,
        "ref_consumer_paths": snapshot.ref_consumer_paths,
        "built_prompt": "built prompt",
        "seed": 679630015510424864,
        "requested_duration": 11,
        "upload_paths": ["c009/task-42/subject1.png"],
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        inject_minimaxh3_workflow_inputs(workflow, **kwargs)  # type: ignore[arg-type]


def test_rejects_preset_and_orphaned_real_workflow_references() -> None:
    snapshot, workflow = _binding_definition()

    preset = copy.deepcopy(workflow)
    preset["137"]["inputs"]["image"] = "preset.png"  # type: ignore[index]
    with pytest.raises(ValueError, match="preset"):
        _inject(preset, snapshot, ["c009/task-42/subject1.png"])

    broken_link = copy.deepcopy(workflow)
    broken_link["186"]["inputs"]["ref_images.ref_image_0"] = [  # type: ignore[index]
        "400",
        0,
    ]
    with pytest.raises(ValueError, match="linked"):
        _inject(broken_link, snapshot, ["c009/task-42/subject1.png"])

    orphan = copy.deepcopy(workflow)
    orphan["999"] = {"class_type": "TestConsumer", "inputs": {"source": ["400", 0]}}
    with pytest.raises(ValueError, match="orphaned"):
        _inject(orphan, snapshot, ["c009/task-42/subject1.png"])
