import copy
import json
from pathlib import Path
from typing import Callable

import pytest

from app.integrations.workflow_binding import (
    WorkflowBindingError,
    load_binding_snapshot,
    load_minimax_binding_snapshot,
)


EXPECTED_HASH = (
    "4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772"
)
EXPECTED_IMAGE_PATHS = (
    "137.inputs.image",
    "139.inputs.image",
    "146.inputs.image",
    "400.inputs.image",
    "401.inputs.image",
    "402.inputs.image",
    "403.inputs.image",
    "404.inputs.image",
    "405.inputs.image",
)
EXPECTED_CONSUMER_PATHS = (
    "186.inputs.ref_images.ref_image_0",
    "186.inputs.ref_images.ref_image_1",
    "186.inputs.ref_images.ref_image_2",
    "186.inputs.ref_images.ref_image_3",
    "186.inputs.ref_images.ref_image_4",
    "186.inputs.ref_images.ref_image_5",
    "186.inputs.ref_images.ref_image_6",
    "186.inputs.ref_images.ref_image_7",
    "186.inputs.ref_images.ref_image_8",
)


def _repo_workflow() -> dict[str, object]:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "workflows"
        / "minimax_h3_ref2v.json"
    )
    return json.loads(workflow_path.read_text(encoding="utf-8"))


def _valid_config() -> dict[str, object]:
    return {
        "workflow": "workflows/minimax_h3_ref2v.json",
        "prompt_path": "138.inputs.value",
        "seed_path": "129.inputs.noise_seed",
        "duration_path": "132.inputs.value",
        "ref_image_paths": list(EXPECTED_IMAGE_PATHS),
        "ref_consumer_paths": list(EXPECTED_CONSUMER_PATHS),
        "optional_refs": False,
        "output_node": "168",
    }


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(value)


def _binding_text(
    config: dict[str, object], *, section: str = "minimaxh3"
) -> str:
    lines = [f"[comfy.{section}]"]
    lines.extend(
        f"{key} = {_toml_value(value)}" for key, value in config.items()
    )
    return "\n".join(lines) + "\n"


def _write_case(
    root: Path,
    *,
    config: dict[str, object] | None = None,
    section: str = "minimaxh3",
    mutate_workflow: Callable[[dict[str, object]], None] | None = None,
    binding_text: str | None = None,
) -> tuple[Path, Path]:
    workflow_root = root / "workflows"
    workflow_root.mkdir(parents=True)
    workflow = copy.deepcopy(_repo_workflow())
    if mutate_workflow is not None:
        mutate_workflow(workflow)
    (workflow_root / "minimax_h3_ref2v.json").write_text(
        json.dumps(workflow, ensure_ascii=False), encoding="utf-8"
    )
    binding_path = workflow_root / "minimaxh3.toml"
    binding_path.write_text(
        _binding_text(_valid_config() if config is None else config, section=section)
        if binding_text is None
        else binding_text,
        encoding="utf-8",
    )
    return root, binding_path


def _assert_rejected(
    root: Path,
    *,
    expected: str,
    config: dict[str, object] | None = None,
    section: str = "minimaxh3",
    mutate_workflow: Callable[[dict[str, object]], None] | None = None,
    binding_text: str | None = None,
) -> None:
    backend_root, binding_path = _write_case(
        root,
        config=config,
        section=section,
        mutate_workflow=mutate_workflow,
        binding_text=binding_text,
    )
    with pytest.raises(WorkflowBindingError) as error:
        load_minimax_binding_snapshot(binding_path, backend_root=backend_root)
    assert expected in str(error.value)


def test_loads_verified_minimax_binding_and_detaches_snapshot() -> None:
    snapshot = load_minimax_binding_snapshot()

    assert snapshot.name == "minimaxh3"
    assert snapshot.workflow_hash == EXPECTED_HASH
    assert snapshot.hash == EXPECTED_HASH
    assert snapshot.prompt_path == "138.inputs.value"
    assert snapshot.seed_path == "129.inputs.noise_seed"
    assert snapshot.duration_path == "132.inputs.value"
    assert snapshot.ref_image_paths == EXPECTED_IMAGE_PATHS
    assert snapshot.ref_consumer_paths == EXPECTED_CONSUMER_PATHS
    assert snapshot.optional_refs is False
    assert snapshot.output_node == "168"
    assert snapshot.definition["138"]["inputs"]["value"] == ""
    assert snapshot.definition["137"]["inputs"]["image"] == (
        "__C009_REFERENCE_01__.png"
    )
    assert snapshot.definition["186"]["inputs"][
        "ref_images.ref_image_0"
    ] == ("137", 0)

    with pytest.raises(TypeError):
        snapshot.definition["138"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.definition["138"]["inputs"]["value"] = "changed"  # type: ignore[index]

    detached = snapshot.workflow_payload()
    detached["definition"]["138"]["inputs"]["value"] = "changed"
    detached["ref_image_paths"][0] = "changed"
    assert snapshot.definition["138"]["inputs"]["value"] == ""
    assert snapshot.ref_image_paths[0] == EXPECTED_IMAGE_PATHS[0]


def test_rejects_invalid_minimax_binding_shapes(tmp_path: Path) -> None:
    missing = _valid_config()
    del missing["duration_path"]
    _assert_rejected(
        tmp_path / "missing-field",
        config=missing,
        expected="invalid fields",
    )

    extra = _valid_config()
    extra["unexpected"] = "no"
    _assert_rejected(
        tmp_path / "extra-field",
        config=extra,
        expected="invalid fields",
    )

    _assert_rejected(
        tmp_path / "missing-section",
        section="zimage",
        expected="invalid fields",
    )
    _assert_rejected(
        tmp_path / "ui-graph",
        mutate_workflow=lambda workflow: workflow.update(
            {"nodes": [], "links": []}
        ),
        expected="UI graph",
    )
    escaped = _valid_config()
    escaped["workflow"] = "../outside.json"
    _assert_rejected(
        tmp_path / "escaped-path",
        config=escaped,
        expected="workflow path must be relative to backend",
    )
    optional = _valid_config()
    optional["optional_refs"] = True
    _assert_rejected(
        tmp_path / "optional-refs",
        config=optional,
        expected="optional_refs must be false",
    )


def test_rejects_reference_count_and_uniqueness(tmp_path: Path) -> None:
    short_images = _valid_config()
    short_images["ref_image_paths"] = list(EXPECTED_IMAGE_PATHS[:-1])
    _assert_rejected(
        tmp_path / "short-images",
        config=short_images,
        expected="ref_image_paths must contain exactly 9 paths",
    )

    duplicate_images = _valid_config()
    duplicate_images["ref_image_paths"] = [
        EXPECTED_IMAGE_PATHS[0],
        EXPECTED_IMAGE_PATHS[0],
        *EXPECTED_IMAGE_PATHS[2:],
    ]
    _assert_rejected(
        tmp_path / "duplicate-images",
        config=duplicate_images,
        expected="ref_image_paths paths must be unique",
    )

    short_consumers = _valid_config()
    short_consumers["ref_consumer_paths"] = list(EXPECTED_CONSUMER_PATHS[:-1])
    _assert_rejected(
        tmp_path / "short-consumers",
        config=short_consumers,
        expected="ref_consumer_paths must contain exactly 9 paths",
    )

    duplicate_consumers = _valid_config()
    duplicate_consumers["ref_consumer_paths"] = [
        EXPECTED_CONSUMER_PATHS[0],
        EXPECTED_CONSUMER_PATHS[0],
        *EXPECTED_CONSUMER_PATHS[2:],
    ]
    _assert_rejected(
        tmp_path / "duplicate-consumers",
        config=duplicate_consumers,
        expected="ref_consumer_paths paths must be unique",
    )


def test_rejects_wrong_reference_leaf_and_consumer(tmp_path: Path) -> None:
    wrong_image_node = _valid_config()
    wrong_image_node["ref_image_paths"] = [
        "138.inputs.value",
        *EXPECTED_IMAGE_PATHS[1:],
    ]
    _assert_rejected(
        tmp_path / "wrong-image-node",
        config=wrong_image_node,
        expected="must reference a LoadImage node",
    )

    wrong_sentinel = lambda workflow: workflow["137"]["inputs"].update(
        {"image": "preset-uuid.png"}
    )
    _assert_rejected(
        tmp_path / "preset-image",
        mutate_workflow=wrong_sentinel,
        expected="C009 reference sentinel",
    )

    wrong_seed = _valid_config()
    wrong_seed["seed_path"] = "138.inputs.value"
    _assert_rejected(
        tmp_path / "wrong-seed-leaf",
        config=wrong_seed,
        expected="seed_path leaf must be an integer",
    )

    wrong_duration = _valid_config()
    wrong_duration["duration_path"] = "138.inputs.value"
    _assert_rejected(
        tmp_path / "wrong-duration-leaf",
        config=wrong_duration,
        expected="duration_path leaf must be a finite number",
    )

    wrong_consumer_path = _valid_config()
    wrong_consumer_path["ref_consumer_paths"] = [
        "186.inputs.ref_images.ref_image_9",
        *EXPECTED_CONSUMER_PATHS[1:],
    ]
    _assert_rejected(
        tmp_path / "wrong-consumer-path",
        config=wrong_consumer_path,
        expected="invalid H3 input path",
    )

    wrong_consumer_link = lambda workflow: workflow["186"]["inputs"].update(
        {"ref_images.ref_image_0": ["139", 0]}
    )
    _assert_rejected(
        tmp_path / "wrong-consumer-link",
        mutate_workflow=wrong_consumer_link,
        expected="not linked to its image node",
    )


def test_rejects_wrong_output_and_missing_input(tmp_path: Path) -> None:
    wrong_output = _valid_config()
    wrong_output["output_node"] = "129"
    _assert_rejected(
        tmp_path / "wrong-output-class",
        config=wrong_output,
        expected="output_node must reference a VHS_VideoCombine node",
    )

    missing_output = _valid_config()
    missing_output["output_node"] = "999"
    _assert_rejected(
        tmp_path / "missing-output",
        config=missing_output,
        expected="output_node does not exist",
    )

    missing_prompt = _valid_config()
    missing_prompt["prompt_path"] = "138.inputs.missing"
    _assert_rejected(
        tmp_path / "missing-prompt",
        config=missing_prompt,
        expected="prompt_path does not exist",
    )


def test_zimage_loader_remains_zimage_only(tmp_path: Path) -> None:
    root = tmp_path
    workflow_root = root / "workflows"
    workflow_root.mkdir()
    (workflow_root / "zimage.json").write_text(
        json.dumps(
            {
                "3": {
                    "inputs": {"seed": 1},
                    "class_type": "KSampler",
                },
                "6": {
                    "inputs": {"text": "prompt"},
                    "class_type": "CLIPTextEncode",
                },
                "9": {
                    "inputs": {"images": ["8", 0]},
                    "class_type": "SaveImage",
                },
            }
        ),
        encoding="utf-8",
    )
    binding_path = workflow_root / "bindings.toml"
    binding_path.write_text(
        "[comfy.zimage]\n"
        'workflow = "workflows/zimage.json"\n'
        'prompt_path = "6.inputs.text"\n'
        'seed_path = "3.inputs.seed"\n'
        'output_node = "9"\n'
        "\n[comfy.minimaxh3]\n"
        'workflow = "workflows/minimax_h3_ref2v.json"\n',
        encoding="utf-8",
    )

    with pytest.raises(WorkflowBindingError, match="invalid fields"):
        load_binding_snapshot(binding_path, backend_root=root)
