import json
from pathlib import Path

import pytest

from app.integrations.workflow_binding import (
    WorkflowBindingError,
    load_binding_snapshot,
)


EXPECTED_HASH = "e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa"


def _write_binding(
    root: Path,
    *,
    workflow: str = "workflows/zimage.json",
    prompt_path: str = "6.inputs.text",
    seed_path: str = "3.inputs.seed",
    output_node: str = "9",
    extra: str = "",
) -> tuple[Path, Path]:
    workflow_dir = root / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    binding_path = workflow_dir / "bindings.toml"
    binding_path.write_text(
        "[comfy.zimage]\n"
        f'workflow = "{workflow}"\n'
        f'prompt_path = "{prompt_path}"\n'
        f'seed_path = "{seed_path}"\n'
        f'output_node = "{output_node}"\n'
        f"{extra}",
        encoding="utf-8",
    )
    return binding_path, workflow_dir / "zimage.json"


def _valid_workflow() -> dict[str, object]:
    return {
        "3": {"inputs": {"seed": 123}, "class_type": "KSampler"},
        "6": {"inputs": {"text": "prompt"}, "class_type": "CLIPTextEncode"},
        "9": {"inputs": {"images": ["8", 0]}, "class_type": "SaveImage"},
    }


def test_loads_verified_zimage_binding_and_hash() -> None:
    snapshot = load_binding_snapshot()

    assert snapshot.name == "zimage"
    assert snapshot.workflow_hash == EXPECTED_HASH
    assert snapshot.hash == EXPECTED_HASH
    assert snapshot.prompt_path == "6.inputs.text"
    assert snapshot.seed_path == "3.inputs.seed"
    assert snapshot.output_node == "9"
    assert snapshot.definition["6"]["inputs"]["text"]

    with pytest.raises(TypeError):
        snapshot.definition["6"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.definition["6"]["inputs"]["text"] = "changed"  # type: ignore[index]

    detached = snapshot.workflow_payload()
    detached["definition"]["6"]["inputs"]["text"] = "changed"
    assert snapshot.definition["6"]["inputs"]["text"] != "changed"


@pytest.mark.parametrize(
    ("workflow", "prompt_path", "seed_path", "output_node", "needle"),
    [
        (b"{", "6.inputs.text", "3.inputs.seed", "9", "invalid"),
        (json.dumps({"nodes": [], "links": []}), "6.inputs.text", "3.inputs.seed", "9", "UI graph"),
        (json.dumps({}), "6.inputs.text", "3.inputs.seed", "9", "non-empty"),
        (json.dumps({"workflow": {}}), "6.inputs.text", "3.inputs.seed", "9", "numeric"),
        (json.dumps({"3": {"inputs": {}, "class_type": "KSampler"}}), "6.inputs.text", "3.inputs.seed", "9", "does not exist"),
    ],
)
def test_rejects_invalid_api_workflow_shapes(
    tmp_path: Path,
    workflow: object,
    prompt_path: str,
    seed_path: str,
    output_node: str,
    needle: str,
) -> None:
    binding_path, workflow_path = _write_binding(
        tmp_path,
        prompt_path=prompt_path,
        seed_path=seed_path,
        output_node=output_node,
    )
    if isinstance(workflow, bytes):
        workflow_path.write_bytes(workflow)
    else:
        workflow_path.write_text(workflow, encoding="utf-8")

    with pytest.raises(WorkflowBindingError, match=needle):
        load_binding_snapshot(binding_path, backend_root=tmp_path)


@pytest.mark.parametrize(
    ("prompt_path", "seed_path", "output_node", "workflow", "needle"),
    [
        ("6.inputs.missing", "3.inputs.seed", "9", _valid_workflow(), "prompt_path"),
        ("6.inputs.text", "3.inputs.seed", "9", {**_valid_workflow(), "6": {"inputs": {"text": 1}, "class_type": "CLIPTextEncode"}}, "prompt_path leaf"),
        ("6.inputs.text", "3.inputs.seed", "9", {**_valid_workflow(), "3": {"inputs": {"seed": True}, "class_type": "KSampler"}}, "seed_path leaf"),
        ("6.inputs.text", "3.inputs.seed.extra", "9", _valid_workflow(), "non-object"),
        ("6.inputs.text", "3.inputs.*", "9", _valid_workflow(), "exact dot-separated"),
        ("6.inputs.text", "3.inputs.seed", "10", _valid_workflow(), "output_node"),
    ],
)
def test_rejects_invalid_paths_and_leaf_types(
    tmp_path: Path,
    prompt_path: str,
    seed_path: str,
    output_node: str,
    workflow: dict[str, object],
    needle: str,
) -> None:
    binding_path, workflow_path = _write_binding(
        tmp_path,
        prompt_path=prompt_path,
        seed_path=seed_path,
        output_node=output_node,
    )
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    with pytest.raises(WorkflowBindingError, match=needle):
        load_binding_snapshot(binding_path, backend_root=tmp_path)


def test_rejects_invalid_binding_sections_and_missing_workflow(tmp_path: Path) -> None:
    binding_path, workflow_path = _write_binding(tmp_path)
    workflow_path.write_text(json.dumps(_valid_workflow()), encoding="utf-8")
    binding_path.write_text(
        "[comfy.zimage]\n"
        'workflow = "workflows/zimage.json"\n'
        'prompt_path = "6.inputs.text"\n'
        'seed_path = "3.inputs.seed"\n'
        'output_node = "9"\n'
        "\n[comfy.minimaxh3]\nworkflow = \"not-allowed.json\"\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowBindingError, match="invalid fields"):
        load_binding_snapshot(binding_path, backend_root=tmp_path)

    missing_binding, missing_workflow = _write_binding(tmp_path / "missing")
    assert not missing_workflow.exists()
    with pytest.raises(WorkflowBindingError, match="does not exist"):
        load_binding_snapshot(missing_binding, backend_root=tmp_path / "missing")
