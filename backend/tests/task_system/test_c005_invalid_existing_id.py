import asyncio
import json
import logging
import os
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _ControlledVLLM:
    calls = 0
    valid_id = 0

    def __init__(self, base_url: str) -> None:
        del base_url

    async def wake(self) -> None:
        return None

    async def structured_chat(self, **request: object) -> dict[str, object]:
        del request
        type(self).calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "assets": [
                                    {
                                        "existing_id": type(self).valid_id,
                                        "type": "character",
                                        "name": "模型改名",
                                        "description": "模型新描述",
                                    },
                                    {
                                        "existing_id": 2147483648,
                                        "type": "scene",
                                        "name": "越界场景",
                                        "description": "越界描述",
                                    },
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def test_out_of_range_existing_id_is_downgraded_to_new_asset(
    monkeypatch, caplog
) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        style_id = project_id = episode_id = task_id = current_asset_id = None
        try:
            connection = await asyncpg.connect(_database_url())
            try:
                style_id = await connection.fetchval(
                    """
                    INSERT INTO styles(name, prompt_fragment)
                    VALUES ($1, 'T10 style') RETURNING id
                    """,
                    "C005 T10 style " + uuid4().hex,
                )
                project_id = await connection.fetchval(
                    """
                    INSERT INTO projects(name, style_id)
                    VALUES ($1, $2) RETURNING id
                    """,
                    "C005 T10 project " + uuid4().hex,
                    style_id,
                )
                episode_id = await connection.fetchval(
                    """
                    INSERT INTO episodes(project_id, seq, title, script_text)
                    VALUES ($1, 1, 'T10 episode', 'T10 script') RETURNING id
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
                payload = {
                    "input_snapshot": {
                        "episode_id": episode_id,
                        "project_id": project_id,
                        "script_revision": 4,
                        "rendered_prompt": "T10 prompt",
                        "model": "T10 model",
                        "temperature": 0.2,
                    },
                    "input_hash": None,
                    "source_revisions": {},
                }
                response = await connection.fetchrow(
                    """
                    INSERT INTO tasks(type, target_id, payload, status, progress)
                    VALUES ('gen_assets', $1, $2::jsonb, 'queued', 0)
                    RETURNING id
                    """,
                    episode_id,
                    json.dumps(payload),
                )
                assert response is not None
                task_id = int(response["id"])
            finally:
                await connection.close()

            monkeypatch.setattr(gen_assets_module, "VLLMClient", _ControlledVLLM)
            _ControlledVLLM.calls = 0
            _ControlledVLLM.valid_id = current_asset_id
            with caplog.at_level(logging.WARNING, logger="app.tasks.gen_assets"):
                await TaskQueue(async_session_factory).run_worker(
                    handlers={"gen_assets": gen_assets_handler},
                    stop_when_idle=True,
                    poll_interval=0.01,
                )

            connection = await asyncpg.connect(_database_url())
            try:
                task = await connection.fetchrow(
                    """
                    SELECT status, error_msg
                    FROM tasks WHERE id = $1
                    """,
                    task_id,
                )
                assets = await connection.fetch(
                    """
                    SELECT id, name, description, source
                    FROM assets WHERE project_id = $1 ORDER BY id
                    """,
                    project_id,
                )
                marker = await connection.fetchval(
                    """
                    SELECT assets_generated_script_revision
                    FROM episodes WHERE id = $1
                    """,
                    episode_id,
                )
            finally:
                await connection.close()

            assert task is not None
            assert task["status"] == "done"
            assert task["error_msg"] is None
            assert marker == 4
            assert [row["name"] for row in assets] == ["原角色", "越界场景"]
            assert assets[0]["id"] == current_asset_id
            assert assets[0]["description"] == "原描述"
            assert assets[0]["source"] == "manual"
            assert assets[1]["description"] == "越界描述"
            assert assets[1]["source"] == "generated"
            assert _ControlledVLLM.calls == 1
            warning = caplog.text
            assert f"task_id={task_id}" in warning
            assert f"episode_id={episode_id}" in warning
            assert f"project_id={project_id}" in warning
            assert "existing_id=2147483648" in warning
            assert "DataError" not in warning
        finally:
            if task_id is not None or episode_id is not None:
                connection = await asyncpg.connect(_database_url())
                try:
                    if task_id is not None:
                        await connection.execute(
                            "DELETE FROM tasks WHERE id = $1", task_id
                        )
                    if project_id is not None:
                        await connection.execute(
                            "DELETE FROM assets WHERE project_id = $1", project_id
                        )
                    if episode_id is not None:
                        await connection.execute(
                            "DELETE FROM episodes WHERE id = $1", episode_id
                        )
                    if project_id is not None:
                        await connection.execute(
                            "DELETE FROM projects WHERE id = $1", project_id
                        )
                    if style_id is not None:
                        await connection.execute(
                            "DELETE FROM styles WHERE id = $1", style_id
                        )
                finally:
                    await connection.close()
            await engine.dispose()

    asyncio.run(run())
