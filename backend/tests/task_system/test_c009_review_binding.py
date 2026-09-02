from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.workflow_binding import WorkflowBindingError, load_minimax_binding_snapshot
from app.main import create_app
from app.services.clip_video_inputs import inject_minimaxh3_workflow_inputs


REFERENCE_IMAGE_PATHS = (
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
REFERENCE_CONSUMER_PATHS = tuple(
    f"186.inputs.ref_images.ref_image_{index}" for index in range(9)
)
WORKFLOW_PATH = Path(__file__).resolve().parents[2] / "workflows" / "minimax_h3_ref2v.json"


class _ProbeClient:
    async def health(self) -> None:
        return None


def _database_url() -> str:
    return settings.DATABASE_URL.get_secret_value().replace("+asyncpg", "", 1)


def _valid_config() -> dict[str, object]:
    return {
        "workflow": "workflows/minimax_h3_ref2v.json",
        "prompt_path": "138.inputs.value",
        "seed_path": "129.inputs.noise_seed",
        "duration_path": "132.inputs.value",
        "ref_image_paths": list(REFERENCE_IMAGE_PATHS),
        "ref_consumer_paths": list(REFERENCE_CONSUMER_PATHS),
        "optional_refs": False,
        "output_node": "168",
    }


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(value)


def _write_case(
    root: Path,
    *,
    config_mutator: Callable[[dict[str, object]], None] | None = None,
    workflow_mutator: Callable[[dict[str, object]], None] | None = None,
) -> Path:
    workflow_root = root / "workflows"
    workflow_root.mkdir(parents=True)
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if workflow_mutator is not None:
        workflow_mutator(workflow)
    (workflow_root / "minimax_h3_ref2v.json").write_text(
        json.dumps(workflow, ensure_ascii=False), encoding="utf-8"
    )

    config = _valid_config()
    if config_mutator is not None:
        config_mutator(config)
    binding_path = workflow_root / "minimaxh3.toml"
    lines = ["[comfy.minimaxh3]"]
    lines.extend(f"{key} = {_toml_value(value)}" for key, value in config.items())
    binding_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return binding_path


async def _insert_queued_task(target_id: int) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO tasks(type, target_id, payload, status, progress)
            VALUES ('gen_clip_video', $1, $2, 'queued', 0)
            RETURNING id
            """,
            target_id,
            json.dumps(
                {
                    "input_snapshot": {},
                    "input_hash": None,
                    "source_revisions": {},
                }
            ),
        )
        assert row is not None
        return int(row["id"])
    finally:
        await connection.close()


async def _task_status(task_id: int) -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        status = await connection.fetchval(
            "SELECT status FROM tasks WHERE id = $1", task_id
        )
        assert status is not None
        return str(status)
    finally:
        await connection.close()


async def _delete_task(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
    finally:
        await connection.close()


def _alias_prompt(config: dict[str, object]) -> None:
    config["prompt_path"] = config["seed_path"]


def _alias_seed(config: dict[str, object]) -> None:
    config["seed_path"] = config["duration_path"]


def _alias_duration(config: dict[str, object]) -> None:
    config["duration_path"] = config["seed_path"]


def _add_preset_load_image(workflow: dict[str, object]) -> None:
    workflow["999"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "preset-reference.png"},
    }


def _add_reference_video_loader(workflow: dict[str, object]) -> None:
    workflow["998"] = {
        "class_type": "LoadVideo",
        "inputs": {"file": "reference.mp4"},
    }


def _bind_output_audio(workflow: dict[str, object]) -> None:
    output = copy.deepcopy(workflow["168"])
    output["inputs"]["audio"] = ["120", 0]  # type: ignore[index]
    workflow["168"] = output


@pytest.mark.parametrize(
    ("case_name", "config_mutator", "workflow_mutator", "expected", "target_id"),
    [
        (
            "wrong-second-segment",
            lambda config: config.update({"prompt_path": "138.not_inputs.value"}),
            None,
            "exact node_id.inputs.input_key path",
            9_221_001,
        ),
        ("prompt-alias", _alias_prompt, None, "distinct input leaves", 9_221_002),
        ("seed-alias", _alias_seed, None, "distinct input leaves", 9_221_003),
        ("duration-alias", _alias_duration, None, "distinct input leaves", 9_221_004),
        (
            "extra-preset-load-image",
            None,
            _add_preset_load_image,
            "LoadImage nodes",
            9_221_005,
        ),
        (
            "reference-video-input",
            None,
            _add_reference_video_loader,
            "reference video",
            9_221_006,
        ),
        (
            "output-audio-input",
            None,
            _bind_output_audio,
            "audio input",
            9_221_007,
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_c009_bad_minimax_bindings_reject_before_worker_claim(
    tmp_path: Path,
    case_name: str,
    config_mutator: Callable[[dict[str, object]], None] | None,
    workflow_mutator: Callable[[dict[str, object]], None] | None,
    expected: str,
    target_id: int,
) -> None:
    binding_path = _write_case(
        tmp_path / case_name,
        config_mutator=config_mutator,
        workflow_mutator=workflow_mutator,
    )
    task_id = asyncio.run(_insert_queued_task(target_id))
    handler_calls: list[int] = []

    async def handler(task, _context) -> None:
        handler_calls.append(task.id)

    application = create_app(
        minimax_binding_path=binding_path,
        minimax_binding_root=tmp_path / case_name,
        task_handlers={"gen_clip_video": handler},
        vllm_client_factory=lambda _base_url: _ProbeClient(),
        comfy_client_factory=lambda _base_url: _ProbeClient(),
    )
    try:
        with pytest.raises(WorkflowBindingError, match=expected):
            with TestClient(application):
                pass
        assert application.state.task_runtime is None
        assert handler_calls == []
        assert asyncio.run(_task_status(task_id)) == "queued"
    finally:
        asyncio.run(_delete_task(task_id))


@pytest.mark.parametrize(
    "reference_count", [pytest.param(1, id="one"), pytest.param(9, id="nine")]
)
def test_c009_valid_minimax_injection_keeps_binding_leaves_and_order(
    reference_count: int,
) -> None:
    snapshot = load_minimax_binding_snapshot()
    workflow = snapshot.workflow_payload()["definition"]
    assert isinstance(workflow, dict)
    original = copy.deepcopy(workflow)
    upload_paths = [
        f"c009/review/subject{index}.png"
        for index in range(1, reference_count + 1)
    ]
    built_prompt = "REVIEW_PROMPT_SENTINEL"
    seed = 123456789012345
    requested_duration = 7

    injected = inject_minimaxh3_workflow_inputs(
        workflow,
        prompt_path=snapshot.prompt_path,
        seed_path=snapshot.seed_path,
        duration_path=snapshot.duration_path,
        ref_image_paths=snapshot.ref_image_paths,
        ref_consumer_paths=snapshot.ref_consumer_paths,
        built_prompt=built_prompt,
        seed=seed,
        requested_duration=requested_duration,
        upload_paths=upload_paths,
    )

    assert workflow == original
    assert injected["138"]["inputs"]["value"] == built_prompt  # type: ignore[index]
    assert injected["129"]["inputs"]["noise_seed"] == seed  # type: ignore[index]
    assert injected["132"]["inputs"]["value"] == requested_duration  # type: ignore[index]
    assert len(
        {
            ("138", "value"),
            ("129", "noise_seed"),
            ("132", "value"),
        }
    ) == 3

    expected_image_node_ids = [
        path.split(".", 1)[0] for path in REFERENCE_IMAGE_PATHS[:reference_count]
    ]
    load_images = {
        node_id: node
        for node_id, node in injected.items()
        if node.get("class_type") == "LoadImage"  # type: ignore[union-attr]
    }
    assert set(load_images) == set(expected_image_node_ids)
    assert [
        load_images[node_id]["inputs"]["image"]  # type: ignore[index]
        for node_id in expected_image_node_ids
    ] == upload_paths

    consumer_inputs = injected["186"]["inputs"]  # type: ignore[index]
    consumer_keys = {
        key for key in consumer_inputs if key.startswith("ref_images.ref_image_")
    }
    assert consumer_keys == {
        f"ref_images.ref_image_{index}" for index in range(reference_count)
    }
    assert {
        key: consumer_inputs[key]
        for key in consumer_keys
    } == {
        f"ref_images.ref_image_{index}": [expected_image_node_ids[index], 0]
        for index in range(reference_count)
    }
    assert "__C009_REFERENCE_" not in json.dumps(injected, ensure_ascii=False)
    assert not any(
        "video" in str(key).casefold()
        for node in injected.values()
        for key in node.get("inputs", {})  # type: ignore[union-attr]
    )
    assert "audio" not in injected["168"]["inputs"]  # type: ignore[index]
