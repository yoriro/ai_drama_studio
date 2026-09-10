from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from app.db.session import async_session_factory, engine
from app.models import Task
from app.services.gen_assets import GeneratedAsset, GeneratedAssetsResponse
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _HandlerVLLM:
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
) -> dict[str, object]:
    return {
        "input_snapshot": {
            "episode_id": episode_id,
            "project_id": project_id,
            "script": "C012 names script",
            "script_revision": script_revision,
            "style": "C012 names style",
            "template_key": "script2assets",
            "template_content": "C012 names template",
            "existing_assets": [],
            "rendered_prompt": "C012 names rendered prompt",
            "model": "C012 names model",
            "temperature": 0.2,
        },
        "input_hash": None,
        "source_revisions": {
            "episode": {"id": episode_id, "script_revision": script_revision},
            "assets": [],
        },
    }


async def _create_fixture() -> tuple[int, int, int, int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            "C012 gen names style " + uuid4().hex,
            "C012 gen names style prompt",
        )
        project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            "C012 gen names project " + uuid4().hex,
            style_id,
        )
        other_project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            "C012 gen names other project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            "INSERT INTO episodes (project_id, seq, title, script_text) "
            "VALUES ($1, 1, 'C012 gen names episode', 'C012 gen names script') RETURNING id",
            project_id,
        )
        existing_asset_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source, revision) "
            "VALUES ($1, 'character', '原资产', '原始描述', 'manual', 1) RETURNING id",
            project_id,
        )
        other_asset_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source, revision) "
            "VALUES ($1, 'scene', '跨项目资产', '跨项目描述', 'manual', 1) RETURNING id",
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


async def _insert_task(
    episode_id: int,
    payload: dict[str, object],
) -> int:
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
    task_id: int,
) -> tuple[list[tuple[object, ...]], tuple[object, ...], tuple[object, ...]]:
    connection = await asyncpg.connect(_database_url())
    try:
        assets = [
            tuple(row)
            for row in await connection.fetch(
                "SELECT id, type, name, description, source, revision "
                "FROM assets WHERE project_id = $1 ORDER BY id",
                project_id,
            )
        ]
        episode = await connection.fetchrow(
            "SELECT assets_generated_script_revision FROM episodes WHERE id = $1",
            episode_id,
        )
        task = await connection.fetchrow(
            "SELECT status, error_msg FROM tasks WHERE id = $1",
            task_id,
        )
        if episode is None or task is None:
            raise AssertionError("C012 gen_assets fixture state disappeared")
        return assets, tuple(episode), tuple(task)
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
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
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


def _response(assets: list[dict[str, object]]) -> dict[str, object]:
    return {"choices": [{"message": {"content": json.dumps({"assets": assets})}}]}


def test_c012_gen_assets_dedupes_candidates_and_preserves_existing_ids(
    monkeypatch,
    caplog,
) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        style_id, project_id, other_project_id, episode_id, existing_asset_id, other_asset_id = (
            await _create_fixture()
        )
        task_ids: list[int] = []
        try:
            task_id = await _insert_task(
                episode_id,
                _task_payload(episode_id, project_id, 7),
            )
            task_ids.append(task_id)
            _HandlerVLLM.responses = [
                _response(
                    [
                        {
                            "existing_id": existing_asset_id,
                            "type": "scene",
                            "name": "模型返回名",
                            "description": "不得覆盖",
                        },
                        {
                            "existing_id": None,
                            "type": "character",
                            "name": "  新角色  ",
                            "description": "首项描述",
                        },
                        {
                            "existing_id": None,
                            "type": "character",
                            "name": "新角色",
                            "description": "重复描述不得覆盖",
                        },
                        {
                            "existing_id": 2_147_483_648,
                            "type": "scene",
                            "name": "越界场景",
                            "description": "越界描述",
                        },
                        {
                            "existing_id": other_asset_id,
                            "type": "scene",
                            "name": "跨项目场景",
                            "description": "跨项目描述",
                        },
                        {
                            "existing_id": 2_147_483_648,
                            "type": "character",
                            "name": " 原资产 ",
                            "description": "同名描述不得插入",
                        },
                    ]
                )
            ]
            _HandlerVLLM.requests = []
            _HandlerVLLM.wake_calls = 0
            monkeypatch.setattr(gen_assets_module, "VLLMClient", _HandlerVLLM)

            with caplog.at_level(logging.WARNING, logger="app.tasks.gen_assets"):
                await _run_worker()

            assets, episode, task = await _read_state(project_id, episode_id, task_id)
            assert [row[2] for row in assets] == [
                "原资产",
                "新角色",
                "越界场景",
                "跨项目场景",
            ]
            assert assets[0][1:] == (
                "character",
                "原资产",
                "原始描述",
                "manual",
                1,
            )
            assert [row[3] for row in assets[1:]] == [
                "首项描述",
                "越界描述",
                "跨项目描述",
            ]
            assert [row[4] for row in assets[1:]] == ["generated"] * 3
            assert episode == (7,)
            assert task[0] == "done"
            assert task[1] is None
            assert len(_HandlerVLLM.requests) == 1
            assert _HandlerVLLM.wake_calls == 1

            warning = caplog.text
            assert f"task_id={task_id}" in warning
            assert f"episode_id={episode_id}" in warning
            assert f"project_id={project_id}" in warning
            assert "response_position=3" in warning
            assert "normalized_name='新角色'" in warning
            assert "reused_asset_id=" in warning
            assert "reason=same_normalized_name_same_type" in warning
            assert "existing_id=2147483648" in warning
            assert "reason=existing_id_out_of_postgres_integer_range" in warning
            assert f"existing_id={other_asset_id}" in warning
            assert "response_position=6" in warning
            assert warning.count("response_position=6") == 2
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


def test_c012_gen_assets_cross_type_conflict_rolls_back_batch(monkeypatch) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        style_id, project_id, other_project_id, episode_id, _existing_asset_id, _other_asset_id = (
            await _create_fixture()
        )
        task_ids: list[int] = []
        try:
            task_id = await _insert_task(
                episode_id,
                _task_payload(episode_id, project_id, 11),
            )
            task_ids.append(task_id)
            _HandlerVLLM.responses = [
                _response(
                    [
                        {
                            "existing_id": None,
                            "type": "character",
                            "name": "本批新增后回滚",
                            "description": "不得保留",
                        },
                        {
                            "existing_id": None,
                            "type": "scene",
                            "name": "原资产",
                            "description": "类型冲突",
                        },
                    ]
                )
            ]
            _HandlerVLLM.requests = []
            _HandlerVLLM.wake_calls = 0
            monkeypatch.setattr(gen_assets_module, "VLLMClient", _HandlerVLLM)
            await _run_worker()

            assets, episode, task = await _read_state(project_id, episode_id, task_id)
            assert [row[2] for row in assets] == ["原资产"]
            assert episode == (None,)
            assert task[0] == "failed"
            assert "normalized asset name conflicts across asset types" in task[1]
            assert "response_position=2" in task[1]
            assert len(_HandlerVLLM.requests) == 1
            assert _HandlerVLLM.wake_calls == 1
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


@pytest.mark.parametrize("name", ["   ", "bad\x00name", "x" * 2001])
def test_c012_generated_asset_name_boundary_is_closed(name: str) -> None:
    with pytest.raises(ValidationError):
        GeneratedAsset(
            existing_id=None,
            type="character",
            name=name,
            description="description",
        )

    normalized = GeneratedAsset(
        existing_id=None,
        type="character",
        name="  保留首尾外空白  ",
        description="description",
    )
    assert normalized.name == "保留首尾外空白"
