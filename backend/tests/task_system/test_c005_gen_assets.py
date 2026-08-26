import asyncio
import json
import logging
import os
from typing import Any
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.models import Task
from app.services.gen_assets import GENERATED_ASSETS_SCHEMA, extract_assets
from app.tasks.queue import ClaimedTask, TaskQueue, WorkerContext


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _delete_task(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
    finally:
        await connection.close()


class _ControlledVLLM:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.wake_calls = 0
        self.chat_calls: list[dict[str, Any]] = []

    async def wake(self) -> None:
        self.wake_calls += 1

    async def structured_chat(self, **request: Any) -> dict[str, object]:
        self.chat_calls.append(request)
        return self.response


def test_gen_assets_uses_snapshot_prompt_and_closed_schema() -> None:
    async def run() -> None:
        target_id = int(uuid4().hex[:7], 16)
        snapshot = {
            "episode_id": target_id,
            "project_id": target_id + 1,
            "script": "入队剧本",
            "script_revision": 1,
            "style": "入队风格",
            "template_key": "script2assets",
            "template_content": "{{existing_assets}} {{style}} {{script}}",
            "existing_assets": [],
            "rendered_prompt": "入队后的完整 prompt",
            "model": "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit",
            "temperature": 0.2,
        }
        payload = {
            "input_snapshot": snapshot,
            "input_hash": None,
            "source_revisions": {
                "episode": {"id": target_id, "script_revision": 1},
                "assets": [],
            },
        }
        async with async_session_factory() as session:
            async with session.begin():
                task_row = Task(
                    type="gen_assets",
                    target_id=target_id,
                    payload=payload,
                    status="queued",
                    progress=0.0,
                )
                session.add(task_row)
                await session.flush()
                task_id = task_row.id
        try:
            queue = TaskQueue(async_session_factory)
            async with async_session_factory() as session:
                async with session.begin():
                    claimed = await queue.claim_next(session)
            assert claimed is not None and claimed.task is not None
            controlled = _ControlledVLLM(
                {
                    "choices": [
                        {"message": {"content": '{"assets": []}'}}
                    ]
                }
            )
            context = WorkerContext(queue, claimed.task, async_session_factory)

            async with async_session_factory() as session:
                async with session.begin():
                    row = await session.get(Task, task_id)
                    assert row is not None
                    row.payload = {
                        **row.payload,
                        "input_snapshot": {
                            **row.payload["input_snapshot"],
                            "script": "数据库后改剧本",
                        },
                    }

            result = await extract_assets(claimed.task, context, controlled)  # type: ignore[arg-type]
            assert result is not None
            assert result.assets == []
            assert controlled.wake_calls == 1
            assert len(controlled.chat_calls) == 1
            request = controlled.chat_calls[0]
            assert request["messages"] == [
                {"role": "user", "content": "入队后的完整 prompt"}
            ]
            assert request["model"] == snapshot["model"]
            assert request["temperature"] == 0.2
            assert request["schema_name"] == "script2assets"
            assert request["schema"] == GENERATED_ASSETS_SCHEMA

            for content in (
                '{"assets":[{"existing_id":null,"type":"prop",'
                '"name":"x","description":"y"}]}',
                '{"assets":[{"existing_id":null,"type":"character",'
                '"name":"x","description":"y","extra":"z"}]}',
                '{"assets":[{"type":"character","name":"x",'
                '"description":"y"}]}',
                "```json\n{\"assets\": []}\n```",
                "not json",
            ):
                controlled.response = {
                    "choices": [{"message": {"content": content}}]
                }
                try:
                    await extract_assets(claimed.task, context, controlled)
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid guided output was accepted")
            assert controlled.wake_calls == 6
            assert len(controlled.chat_calls) == 6
        finally:
            await _delete_task(task_id)
            await engine.dispose()

    asyncio.run(run())


async def _cleanup_merge(
    task_id: int,
    episode_id: int,
    project_ids: list[int],
    style_id: int,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
        await connection.execute(
            "DELETE FROM assets WHERE project_id = ANY($1::int[])", project_ids
        )
        await connection.execute("DELETE FROM episodes WHERE id = $1", episode_id)
        await connection.execute(
            "DELETE FROM projects WHERE id = ANY($1::int[])", project_ids
        )
        await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def test_gen_assets_incremental_merge_handles_existing_and_invalid_ids(
    caplog,
) -> None:
    async def run() -> None:
        from app.services.gen_assets import GeneratedAsset, GeneratedAssetsResponse
        from app.tasks.gen_assets import merge_generated_assets

        connection = await asyncpg.connect(_database_url())
        style_id = project_id = other_project_id = episode_id = task_id = None
        current_asset_id = other_asset_id = None
        try:
            style_id = await connection.fetchval(
                """
                INSERT INTO styles(name, prompt_fragment)
                VALUES ($1, 'merge style') RETURNING id
                """,
                "C005 merge style " + uuid4().hex,
            )
            project_id = await connection.fetchval(
                """
                INSERT INTO projects(name, style_id)
                VALUES ($1, $2) RETURNING id
                """,
                "C005 merge project " + uuid4().hex,
                style_id,
            )
            other_project_id = await connection.fetchval(
                """
                INSERT INTO projects(name, style_id)
                VALUES ($1, $2) RETURNING id
                """,
                "C005 other project " + uuid4().hex,
                style_id,
            )
            episode_id = await connection.fetchval(
                """
                INSERT INTO episodes(project_id, seq, title, script_text)
                VALUES ($1, 1, 'Merge episode', 'snapshot') RETURNING id
                """,
                project_id,
            )
            current_asset_id = await connection.fetchval(
                """
                INSERT INTO assets(project_id, type, name, description, source)
                VALUES ($1, 'character', '原角色', '原描述', 'manual')
                RETURNING id
                """,
                project_id,
            )
            other_asset_id = await connection.fetchval(
                """
                INSERT INTO assets(project_id, type, name, description, source)
                VALUES ($1, 'scene', '别的场景', '别的描述', 'manual')
                RETURNING id
                """,
                other_project_id,
            )
            task_id = await connection.fetchval(
                """
                INSERT INTO tasks(type, target_id, payload, status, progress)
                VALUES ('gen_assets', $1, $2::jsonb, 'running', 0.2)
                RETURNING id
                """,
                episode_id,
                json.dumps(
                    {
                        "input_snapshot": {
                            "episode_id": episode_id,
                            "project_id": project_id,
                            "script_revision": 3,
                        },
                        "input_hash": None,
                        "source_revisions": {},
                    }
                ),
            )
        finally:
            await connection.close()

        assert all(
            value is not None
            for value in (
                style_id,
                project_id,
                other_project_id,
                episode_id,
                task_id,
                current_asset_id,
                other_asset_id,
            )
        )
        task = ClaimedTask(
            id=task_id,
            type="gen_assets",
            target_id=episode_id,
            request_id=None,
            payload={
                "input_snapshot": {
                    "episode_id": episode_id,
                    "project_id": project_id,
                    "script_revision": 3,
                },
                "input_hash": None,
                "source_revisions": {},
            },
        )
        result = GeneratedAssetsResponse(
            assets=[
                GeneratedAsset(
                    existing_id=None,
                    type="scene",
                    name="新场景",
                    description="新场景描述",
                ),
                GeneratedAsset(
                    existing_id=current_asset_id,
                    type="scene",
                    name="不得覆盖",
                    description="不得覆盖",
                ),
                GeneratedAsset(
                    existing_id=2147483647,
                    type="character",
                    name="伪造角色",
                    description="伪造描述",
                ),
                GeneratedAsset(
                    existing_id=other_asset_id,
                    type="scene",
                    name="跨项目场景",
                    description="跨项目描述",
                ),
            ]
        )
        try:
            with caplog.at_level(logging.WARNING, logger="app.tasks.gen_assets"):
                await merge_generated_assets(task, result)
            connection = await asyncpg.connect(_database_url())
            try:
                rows = await connection.fetch(
                    """
                    SELECT id, project_id, type, name, description, source, revision
                    FROM assets WHERE project_id = $1 ORDER BY id
                    """,
                    project_id,
                )
                marker = await connection.fetchval(
                    "SELECT assets_generated_script_revision FROM episodes WHERE id = $1",
                    episode_id,
                )
                image_count = await connection.fetchval(
                    """
                    SELECT count(*) FROM asset_images
                    WHERE asset_id = ANY($1::int[])
                    """,
                    [row["id"] for row in rows],
                )
            finally:
                await connection.close()
            assert marker == 3
            assert image_count == 0
            assert [row["name"] for row in rows] == [
                "原角色",
                "新场景",
                "伪造角色",
                "跨项目场景",
            ]
            assert all(row["source"] == "manual" for row in rows[:1])
            assert all(row["source"] == "generated" for row in rows[1:])
            assert rows[0]["description"] == "原描述"
            warning = caplog.text
            assert f"task_id={task_id}" in warning
            assert f"episode_id={episode_id}" in warning
            assert f"project_id={project_id}" in warning
            assert "existing_id=2147483647" in warning
            assert f"existing_id={other_asset_id}" in warning
        finally:
            await _cleanup_merge(
                task_id,
                episode_id,
                [project_id, other_project_id],
                style_id,
            )
            await engine.dispose()

    asyncio.run(run())
