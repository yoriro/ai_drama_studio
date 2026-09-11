from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.models import Task
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _ReuseVLLM:
    responses: list[dict[str, object]] = []
    requests: list[dict[str, Any]] = []
    wake_calls = 0

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def wake(self) -> None:
        type(self).wake_calls += 1

    async def structured_chat(self, **request: Any) -> dict[str, object]:
        type(self).requests.append(request)
        return type(self).responses.pop(0)


def _task_payload(
    episode_id: int,
    project_id: int,
    script_revision: int,
    prompt: str,
) -> dict[str, object]:
    return {
        "input_snapshot": {
            "episode_id": episode_id,
            "project_id": project_id,
            "script": "C012 existing asset reuse",
            "script_revision": script_revision,
            "style": "C012 reuse style",
            "template_key": "script2assets",
            "template_content": "C012 reuse template",
            "existing_assets": [],
            "rendered_prompt": prompt,
            "model": "C012 reuse model",
            "temperature": 0.2,
        },
        "input_hash": None,
        "source_revisions": {
            "episode": {"id": episode_id, "script_revision": script_revision},
            "assets": [],
        },
    }


def _response(assets: list[dict[str, object]]) -> dict[str, object]:
    return {"choices": [{"message": {"content": json.dumps({"assets": assets})}}]}


async def _create_fixture() -> tuple[int, int, int, int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            "C012 reuse style " + uuid4().hex,
            "C012 reuse style prompt",
        )
        project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            "C012 reuse project " + uuid4().hex,
            style_id,
        )
        other_project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            "C012 reuse other project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            "INSERT INTO episodes (project_id, seq, title, script_text) "
            "VALUES ($1, 1, 'C012 reuse episode', 'C012 reuse script') RETURNING id",
            project_id,
        )
        existing_asset_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source, revision) "
            "VALUES ($1, 'character', '保留资产', '原始描述', 'manual', 4) RETURNING id",
            project_id,
        )
        other_asset_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source, revision) "
            "VALUES ($1, 'scene', '跨项目资产', '跨项目描述', 'manual', 2) RETURNING id",
            other_project_id,
        )
        return (
            int(style_id),
            int(project_id),
            int(other_project_id),
            int(episode_id),
            int(existing_asset_id),
            int(other_asset_id),
        )
    finally:
        await connection.close()


async def _insert_task(episode_id: int, payload: dict[str, object]) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            task = Task(
                type="gen_assets",
                target_id=episode_id,
                payload=payload,
                status="queued",
                progress=0.0,
            )
            session.add(task)
            await session.flush()
            return int(task.id)


async def _run_worker() -> None:
    queue = TaskQueue(async_session_factory)
    await queue.run_worker(
        handlers={"gen_assets": gen_assets_handler},
        stop_when_idle=True,
        poll_interval=0.01,
    )


async def _read_state(
    project_id: int,
    episode_id: int,
    task_ids: list[int],
) -> tuple[list[tuple[object, ...]], object, list[tuple[object, ...]]]:
    connection = await asyncpg.connect(_database_url())
    try:
        assets = [
            tuple(row)
            for row in await connection.fetch(
                "SELECT id, project_id, type, name, description, source, revision "
                "FROM assets WHERE project_id = $1 ORDER BY id",
                project_id,
            )
        ]
        marker = await connection.fetchval(
            "SELECT assets_generated_script_revision FROM episodes WHERE id = $1",
            episode_id,
        )
        tasks = [
            tuple(row)
            for row in await connection.fetch(
                "SELECT id, status, error_msg FROM tasks "
                "WHERE id = ANY($1::int[]) ORDER BY id",
                task_ids,
            )
        ]
        return assets, marker, tasks
    finally:
        await connection.close()


async def _cleanup(
    style_id: int,
    project_id: int,
    other_project_id: int,
    episode_id: int,
    task_ids: list[int],
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids)
        await connection.execute("DELETE FROM episodes WHERE id = $1", episode_id)
        await connection.execute("DELETE FROM assets WHERE project_id = $1", project_id)
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", other_project_id
        )
        await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", other_project_id
        )
        await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def test_c012_gen_assets_reuse_skips_name_validation_for_existing_ids(
    monkeypatch,
    caplog,
) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        (
            style_id,
            project_id,
            other_project_id,
            episode_id,
            existing_asset_id,
            other_asset_id,
        ) = await _create_fixture()
        task_ids: list[int] = []
        try:
            responses = [
                _response(
                    [
                        {
                            "existing_id": existing_asset_id,
                            "type": "character",
                            "name": "   ",
                            "description": "不得覆盖空白名称",
                        },
                        {
                            "existing_id": existing_asset_id,
                            "type": "character",
                            "name": "bad\x00name",
                            "description": "不得覆盖 NUL 名称",
                        },
                        {
                            "existing_id": existing_asset_id,
                            "type": "character",
                            "name": "x" * 2001,
                            "description": "不得覆盖超长名称",
                        },
                    ]
                ),
                _response(
                    [
                        {
                            "existing_id": 2_147_483_648,
                            "type": "character",
                            "name": "保留资产",
                            "description": "通过真实名称冲突复用",
                        }
                    ]
                ),
                _response(
                    [
                        {
                            "existing_id": None,
                            "type": "character",
                            "name": "   ",
                            "description": "新增候选空白名称",
                        }
                    ]
                ),
                _response(
                    [
                        {
                            "existing_id": 2_147_483_648,
                            "type": "character",
                            "name": "bad\x00name",
                            "description": "非法 ID NUL 名称",
                        }
                    ]
                ),
                _response(
                    [
                        {
                            "existing_id": other_asset_id,
                            "type": "scene",
                            "name": "x" * 2001,
                            "description": "跨项目超长名称",
                        }
                    ]
                ),
            ]
            _ReuseVLLM.requests = []
            _ReuseVLLM.wake_calls = 0
            monkeypatch.setattr(gen_assets_module, "VLLMClient", _ReuseVLLM)

            before_assets, before_marker, _ = await _read_state(
                project_id, episode_id, []
            )
            assert before_marker is None
            assert before_assets == [
                (
                    existing_asset_id,
                    project_id,
                    "character",
                    "保留资产",
                    "原始描述",
                    "manual",
                    4,
                )
            ]

            prompts = [
                "reuse-invalid-return-name",
                "reuse-by-name",
                "new-blank-name",
                "invalid-id-nul-name",
                "cross-project-long-name",
            ]
            revisions = [41, 42, 43, 44, 45]
            with caplog.at_level(logging.WARNING, logger="app.tasks.gen_assets"):
                for revision, prompt, response in zip(revisions, prompts, responses):
                    _ReuseVLLM.responses = [response]
                    task_ids.append(
                        await _insert_task(
                            episode_id,
                            _task_payload(episode_id, project_id, revision, prompt),
                        )
                    )
                    await _run_worker()

            assets, marker, tasks = await _read_state(
                project_id, episode_id, task_ids
            )
            assert assets == before_assets
            assert marker == 42
            assert [row[1] for row in tasks] == [
                "done",
                "done",
                "failed",
                "failed",
                "failed",
            ]
            assert "name must not be blank" in (tasks[2][2] or "")
            assert "name must not contain NUL" in (tasks[3][2] or "")
            assert "name is too long" in (tasks[4][2] or "")
            assert len(_ReuseVLLM.requests) == 5
            assert _ReuseVLLM.wake_calls == 5
            assert all(
                request["schema_name"] == "script2assets"
                for request in _ReuseVLLM.requests
            )

            warning = caplog.text
            assert f"existing_id=2147483648" in warning
            assert f"reused_asset_id={existing_asset_id}" in warning
            assert "reason=same_normalized_name_same_type" in warning
        finally:
            await _cleanup(
                style_id,
                project_id,
                other_project_id,
                episode_id,
                task_ids,
            )
            await engine.dispose()

    asyncio.run(run())
