import asyncio
import copy
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_binding_snapshot
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.tasks.queue import TaskQueue, TaskRequestConflictError


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 T6 style " + uuid4().hex,
            "水墨写实",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 T6 project " + uuid4().hex,
            style_id,
        )
        asset_ids = []
        for name, description in (
            ("林夏", "黑发白衬衫"),
            ("顾言", "深色外套"),
        ):
            asset_id = await connection.fetchval(
                """
                INSERT INTO assets
                    (project_id, type, name, description, source, revision)
                VALUES ($1, 'character', $2, $3, 'manual', 1)
                RETURNING id
                """,
                project_id,
                name,
                description,
            )
            asset_ids.append(asset_id)
        return {
            "style_id": style_id,
            "project_id": project_id,
            "asset_id": asset_ids[0],
            "other_asset_id": asset_ids[1],
        }
    finally:
        await connection.close()


async def _read_template() -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        content = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'zimage'"
        )
        assert isinstance(content, str)
        return content
    finally:
        await connection.close()


async def _write_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
            content,
        )
    finally:
        await connection.close()


async def _set_task_status(task_id: int, status: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE tasks SET status = $1 WHERE id = $2", status, task_id
        )
    finally:
        await connection.close()


async def _mutate_sources(fixture: dict[str, int], *, template: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE assets
            SET name = '改名后', description = '描述后', revision = 2
            WHERE id = $1
            """,
            fixture["asset_id"],
        )
        await connection.execute(
            "UPDATE styles SET prompt_fragment = '风格后' WHERE id = $1",
            fixture["style_id"],
        )
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
            template,
        )
    finally:
        await connection.close()


async def _fetch_tasks(task_ids: list[int]) -> list[dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT id, type, target_id, request_id, status, progress, payload
            FROM tasks
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            task_ids,
        )
        result: list[dict[str, object]] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            assert isinstance(payload, dict)
            result.append(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "target_id": row["target_id"],
                    "request_id": row["request_id"],
                    "status": row["status"],
                    "progress": row["progress"],
                    "payload": payload,
                }
            )
        return result
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int], task_ids: list[int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        await connection.execute(
            "DELETE FROM assets WHERE id = ANY($1::int[])",
            [fixture["asset_id"], fixture["other_asset_id"]],
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


class _StartGate:
    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._lock = asyncio.Lock()
        self._open = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._arrived += 1
            if self._arrived == self._parties:
                self._open.set()
        await self._open.wait()


async def _enqueue(
    fixture: dict[str, int],
    binding,
    *,
    request_id: str | None,
    user_note: str | None,
) -> object:
    async with async_session_factory() as session:
        return await enqueue_generate_asset_image(
            session,
            TaskQueue(async_session_factory),
            fixture["asset_id"],
            user_note=user_note,
            request_id=request_id,
            workflow_binding=binding,
        )


def test_request_id_concurrency_reuses_one_frozen_task_and_conflicts() -> None:
    async def run() -> None:
        original_template = await _read_template()
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        fixture = await _create_fixture()
        binding = load_binding_snapshot()
        task_ids: list[int] = []
        try:
            await _write_template(template)
            gate = _StartGate(3)

            async def attempt() -> object:
                await gate.wait()
                return await _enqueue(
                    fixture,
                    binding,
                    request_id=" abc ",
                    user_note=None,
                )

            results = await asyncio.gather(*(attempt() for _ in range(3)))
            result_ids = [result.task.id for result in results]
            task_ids.extend(set(result_ids))
            assert result_ids == [result_ids[0]] * 3
            rows = await _fetch_tasks(task_ids)
            assert len(rows) == 1
            row = rows[0]
            assert row["type"] == "gen_asset_image"
            assert row["target_id"] == fixture["asset_id"]
            assert row["request_id"] == "abc"
            assert row["status"] == "queued"
            payload = row["payload"]
            assert isinstance(payload, dict)
            snapshot = payload["input_snapshot"]
            assert isinstance(snapshot, dict)
            assert snapshot["seed"] == 1782929867419795085
            assert snapshot["comfy_prompt_id"] == (
                "f0faf273-5fe9-5726-98be-3d449efdbe8d"
            )
            assert snapshot["user_note"] is None

            await _set_task_status(result_ids[0], "done")
            await _mutate_sources(
                fixture,
                template="asset={{asset}}|style={{style}}|note={{user_note}}|changed",
            )
            replay = await _enqueue(
                fixture,
                binding,
                request_id="abc",
                user_note=None,
            )
            assert replay.task.id == result_ids[0]
            assert replay.created is False
            replay_payload = replay.task.payload
            assert replay_payload == payload

            with pytest.raises(TaskRequestConflictError):
                await _enqueue(
                    {**fixture, "asset_id": fixture["other_asset_id"]},
                    binding,
                    request_id="abc",
                    user_note=None,
                )
            with pytest.raises(TaskRequestConflictError):
                await _enqueue(
                    fixture,
                    binding,
                    request_id="abc",
                    user_note="different note",
                )
        finally:
            await _write_template(original_template)
            await _cleanup_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())


def test_request_without_id_allows_independent_active_draws() -> None:
    async def run() -> None:
        original_template = await _read_template()
        fixture = await _create_fixture()
        binding = load_binding_snapshot()
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        task_ids: list[int] = []
        try:
            await _write_template(template)
            gate = _StartGate(3)

            async def attempt() -> object:
                await gate.wait()
                return await _enqueue(
                    fixture,
                    binding,
                    request_id=None,
                    user_note=None,
                )

            results = await asyncio.gather(*(attempt() for _ in range(3)))
            task_ids = [result.task.id for result in results]
            assert len(set(task_ids)) == 3
            rows = await _fetch_tasks(task_ids)
            assert len(rows) == 3
            assert {row["status"] for row in rows} == {"queued"}
            assert {row["request_id"] for row in rows} == {None}
            snapshots = [row["payload"]["input_snapshot"] for row in rows]
            assert len({snapshot["seed"] for snapshot in snapshots}) == 3
            assert len({snapshot["comfy_prompt_id"] for snapshot in snapshots}) == 3
            assert len({json.dumps(snapshot, sort_keys=True) for snapshot in snapshots}) == 3
        finally:
            await _write_template(original_template)
            await _cleanup_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())


def test_payload_snapshot_survives_source_changes_and_worker_uses_copy(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        original_template = await _read_template()
        fixture = await _create_fixture()
        task_ids: list[int] = []
        workflow_path = tmp_path / "zimage.json"
        binding_path = tmp_path / "bindings.toml"
        workflow = {
            "3": {"inputs": {"seed": 11}, "class_type": "KSampler"},
            "6": {"inputs": {"text": "old prompt"}, "class_type": "CLIPTextEncode"},
            "9": {"inputs": {}, "class_type": "SaveImage"},
        }
        workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
        binding_path.write_text(
            "[comfy.zimage]\n"
            'workflow = "zimage.json"\n'
            'prompt_path = "6.inputs.text"\n'
            'seed_path = "3.inputs.seed"\n'
            'output_node = "9"\n',
            encoding="utf-8",
        )
        binding = load_binding_snapshot(binding_path, backend_root=tmp_path)
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        try:
            await _write_template(template)
            result = await _enqueue(
                fixture,
                binding,
                request_id=None,
                user_note="before",
            )
            task_ids.append(result.task.id)
            frozen_payload = copy.deepcopy(result.task.payload)

            workflow["3"]["inputs"]["seed"] = 999
            workflow["6"]["inputs"]["text"] = "changed on disk"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            await _mutate_sources(
                fixture,
                template="asset={{asset}}|style={{style}}|note={{user_note}}|changed",
            )

            observed: dict[str, object] = {}

            async def handler(task, _context) -> None:
                observed["payload"] = copy.deepcopy(task.payload)

            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            assert observed["payload"] == frozen_payload
            assert observed["payload"]["input_snapshot"]["workflow"]["definition"]["6"]["inputs"]["text"] == "old prompt"
        finally:
            await _write_template(original_template)
            await _cleanup_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())
