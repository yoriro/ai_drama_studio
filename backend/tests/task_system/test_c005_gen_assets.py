import asyncio
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
