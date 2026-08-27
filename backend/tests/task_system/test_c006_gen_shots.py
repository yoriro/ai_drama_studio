import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.services.generate_shots import build_generate_shots_response_format
from app.tasks.gen_shots import gen_shots_handler
from app.tasks.queue import TaskQueue
from app.models import Task


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _FakeVLLM:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.base_url: str | None = None
        self.wake_calls = 0
        self.chat_calls: list[dict[str, Any]] = []

    async def wake(self) -> None:
        self.wake_calls += 1

    async def structured_chat(self, **request: Any) -> dict[str, object]:
        self.chat_calls.append(request)
        return self.response


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '测试风格')
            RETURNING id
            """,
            "C006 T4 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T4 project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'T4 episode', '入队剧本')
            RETURNING id
            """,
            project_id,
        )
        target_assets: list[tuple[str, str, str]] = [
            ("character", "林夏", "短发，穿蓝色外套"),
            ("scene", "旧车站", "雨夜的空旷站台"),
            ("scene", "河岸", "清晨的河岸"),
            ("prop", "旧伞", "一把黑色雨伞"),
        ]
        asset_ids: list[int] = []
        for asset_type, name, description in target_assets:
            asset_id = await connection.fetchval(
                """
                INSERT INTO assets
                    (project_id, type, name, description, source)
                VALUES ($1, $2, $3, $4, 'manual')
                RETURNING id
                """,
                project_id,
                asset_type,
                name,
                description,
            )
            asset_ids.append(asset_id)

        foreign_style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '跨项目风格')
            RETURNING id
            """,
            "C006 T4 foreign style " + uuid4().hex,
        )
        foreign_project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T4 foreign project " + uuid4().hex,
            foreign_style_id,
        )
        foreign_asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source)
            VALUES ($1, 'character', '外部人物', '另一个项目的人物', 'manual')
            RETURNING id
            """,
            foreign_project_id,
        )

        shot_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 2.5, '中景', '固定', '旧镜头', '', 'normal', 3)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            asset_ids[0],
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, requested_duration)
            VALUES ($1, 5)
            RETURNING id
            """,
            episode_id,
        )
        video_id = await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration)
            VALUES ($1, $2, $3, 1, 5)
            RETURNING id
            """,
            clip_id,
            f"projects/{project_id}/episodes/{episode_id}/clips/{clip_id}/1.mp4",
            uuid4().hex,
        )
        return {
            "style_id": style_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "asset_ids": asset_ids,
            "valid_asset_ids": asset_ids[:3],
            "foreign_style_id": foreign_style_id,
            "foreign_project_id": foreign_project_id,
            "foreign_asset_id": foreign_asset_id,
            "shot_id": shot_id,
            "clip_id": clip_id,
            "video_id": video_id,
        }
    finally:
        await connection.close()


async def _cleanup_fixture(
    fixture: dict[str, object], task_ids: list[int]
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM shots WHERE id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["foreign_project_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["foreign_project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = ANY($1::int[])",
            [fixture["style_id"], fixture["foreign_style_id"]],
        )
    finally:
        await connection.close()


def _build_payload(
    fixture: dict[str, object],
    *,
    include_foreign_asset: bool = False,
) -> dict[str, object]:
    valid_ids = list(fixture["valid_asset_ids"])
    assets = [
        {
            "id": valid_ids[0],
            "type": "character",
            "name": "林夏",
            "description": "短发，穿蓝色外套",
        },
        {
            "id": valid_ids[1],
            "type": "scene",
            "name": "旧车站",
            "description": "雨夜的空旷站台",
        },
        {
            "id": valid_ids[2],
            "type": "scene",
            "name": "河岸",
            "description": "清晨的河岸",
        },
    ]
    schema_ids = valid_ids
    if include_foreign_asset:
        foreign_id = fixture["foreign_asset_id"]
        assets.append(
            {
                "id": foreign_id,
                "type": "character",
                "name": "外部人物",
                "description": "另一个项目的人物",
            }
        )
        schema_ids = [*valid_ids, foreign_id]
    snapshot = {
        "episode_id": fixture["episode_id"],
        "project_id": fixture["project_id"],
        "script": "入队剧本",
        "script_revision": 1,
        "style": "测试风格",
        "template_key": "script2shots",
        "template_content": "模板",
        "assets": assets,
        "rendered_prompt": "入队后的完整分镜 prompt",
        "model": "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit",
        "temperature": 0.2,
        "guided_json_schema": build_generate_shots_response_format(schema_ids),
        "replacement_snapshot": {
            "shots": [{"id": fixture["shot_id"], "revision": 3}],
            "clips": [{"id": fixture["clip_id"], "revision": 1}],
            "clip_video_ids": [fixture["video_id"]],
            "clip_media": [
                {
                    "kind": "clip_video",
                    "id": fixture["video_id"],
                    "path": "projects/old.mp4",
                }
            ],
        },
    }
    return {
        "input_snapshot": snapshot,
        "input_hash": None,
        "source_revisions": {
            "episode": {
                "id": fixture["episode_id"],
                "script_revision": 1,
            },
            "assets": [{"id": asset_id, "revision": 1} for asset_id in schema_ids],
            "shots": [{"id": fixture["shot_id"], "revision": 3}],
            "clips": [{"id": fixture["clip_id"], "revision": 1}],
        },
    }


async def _insert_task(
    payload: dict[str, object],
    episode_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    async with session_factory() as session:
        async with session.begin():
            task = Task(
                type="gen_shots",
                target_id=episode_id,
                request_id=None,
                payload=payload,
                status="queued",
                progress=0.0,
            )
            session.add(task)
            await session.flush()
            return task.id


async def _run_task(
    task_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del task_id
    queue = TaskQueue(session_factory)
    await queue.run_worker(
        handlers={"gen_shots": gen_shots_handler},
        poll_interval=0.01,
        stop_when_idle=True,
    )


async def _read_task(
    task_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str | None]:
    async with session_factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task.status, task.error_msg


async def _structure_counts(fixture: dict[str, object]) -> tuple[int, int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        return (
            await connection.fetchval(
                "SELECT count(*) FROM shots WHERE episode_id = $1",
                fixture["episode_id"],
            ),
            await connection.fetchval(
                "SELECT count(*) FROM clips WHERE episode_id = $1",
                fixture["episode_id"],
            ),
            await connection.fetchval(
                """
                SELECT count(*) FROM clip_videos
                WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                """,
                fixture["episode_id"],
            ),
            await connection.fetchval(
                """
                SELECT count(*) FROM shot_assets
                WHERE shot_id IN (SELECT id FROM shots WHERE episode_id = $1)
                """,
                fixture["episode_id"],
            ),
        )
    finally:
        await connection.close()


def _response(value: object) -> dict[str, object]:
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"choices": [{"message": {"content": content}}]}


def _shot(
    *,
    order: int = 1,
    duration_est: object = 2.5,
    shot_type: str = "近景",
    camera: str = "固定",
    asset_ids: list[int] | None = None,
) -> dict[str, object]:
    return {
        "order": order,
        "duration_est": duration_est,
        "shot_type": shot_type,
        "camera": camera,
        "description": "人物站在站台边缘，雨水沿着伞面滑落",
        "dialogue": "",
        "asset_ids": [] if asset_ids is None else asset_ids,
    }


def test_gen_shots_uses_snapshot_prompt_and_dynamic_schema(monkeypatch) -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.services.gen_shots.async_session_factory", session_factory)
        task_ids: list[int] = []
        try:
            payload = _build_payload(fixture)
            output = {
                "shots": [
                    _shot(order=1, asset_ids=[]),
                    _shot(
                        order=2,
                        asset_ids=[
                            fixture["valid_asset_ids"][1],
                            fixture["valid_asset_ids"][2],
                        ],
                    ),
                ]
            }
            fake = _FakeVLLM(_response(output))
            monkeypatch.setattr(
                "app.tasks.gen_shots.VLLMClient",
                lambda base_url: fake,
            )
            task_id = await _insert_task(
                payload, fixture["episode_id"], session_factory
            )
            task_ids.append(task_id)
            before = await _structure_counts(fixture)
            await _run_task(task_id, session_factory)
            status, error_msg = await _read_task(task_id, session_factory)
            assert status == "done"
            assert error_msg is None
            assert fake.wake_calls == 1
            assert len(fake.chat_calls) == 1
            request = fake.chat_calls[0]
            assert request["messages"] == [
                {"role": "user", "content": "入队后的完整分镜 prompt"}
            ]
            assert request["model"] == "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit"
            assert request["temperature"] == 0.2
            assert request["schema_name"] == "script2shots"
            stored_schema = payload["input_snapshot"]["guided_json_schema"]
            assert request["schema"] == stored_schema["json_schema"]["schema"]
            assert request["schema"]["properties"]["shots"]["items"]["properties"]["asset_ids"]["items"]["enum"] == fixture["valid_asset_ids"]
            assert "system" not in request["messages"][0]
            assert await _structure_counts(fixture) == before
            assert app.state.task_handlers["gen_shots"] is gen_shots_handler
        finally:
            await _cleanup_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())


def test_gen_shots_rejects_invalid_output(monkeypatch) -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.services.gen_shots.async_session_factory", session_factory)
        task_ids: list[int] = []
        try:
            duplicate_id = fixture["valid_asset_ids"][0]
            invalid_cases = [
                ("解释文字", "vLLM response is not a valid"),
                (
                    {"shots": [], "extra": True},
                    "vLLM response is not a valid",
                ),
                (
                    {"shots": [_shot(shot_type="非法")]},
                    "vLLM response is not a valid",
                ),
                (
                    {"shots": [_shot(duration_est=0)]},
                    "vLLM response is not a valid",
                ),
                (
                    {"shots": [_shot(duration_est=6)]},
                    "vLLM response is not a valid",
                ),
                (
                    {"shots": [_shot(order=1), _shot(order=3)]},
                    "continuous sequence",
                ),
                (
                    {"shots": [_shot(asset_ids=[duplicate_id, duplicate_id])]},
                    "duplicate asset ids",
                ),
                (
                    {"shots": [_shot(asset_ids=[999999999])]},
                    "outside the snapshot",
                ),
            ]
            for output, error_fragment in invalid_cases:
                payload = _build_payload(fixture)
                fake = _FakeVLLM(_response(output))
                monkeypatch.setattr(
                    "app.tasks.gen_shots.VLLMClient",
                    lambda base_url, current=fake: current,
                )
                task_id = await _insert_task(
                    payload, fixture["episode_id"], session_factory
                )
                task_ids.append(task_id)
                before = await _structure_counts(fixture)
                await _run_task(task_id, session_factory)
                status, error_msg = await _read_task(task_id, session_factory)
                assert status == "failed"
                assert error_msg is not None
                assert error_fragment in error_msg
                assert fake.wake_calls == 1
                assert len(fake.chat_calls) == 1
                assert await _structure_counts(fixture) == before

            payload = _build_payload(fixture, include_foreign_asset=True)
            foreign_output = {
                "shots": [_shot(asset_ids=[fixture["foreign_asset_id"]])]
            }
            fake = _FakeVLLM(_response(foreign_output))
            monkeypatch.setattr(
                "app.tasks.gen_shots.VLLMClient",
                lambda base_url, current=fake: current,
            )
            task_id = await _insert_task(
                payload, fixture["episode_id"], session_factory
            )
            task_ids.append(task_id)
            before = await _structure_counts(fixture)
            await _run_task(task_id, session_factory)
            status, error_msg = await _read_task(task_id, session_factory)
            assert status == "failed"
            assert error_msg is not None
            assert "no longer valid for the project" in error_msg
            assert fake.wake_calls == 1
            assert len(fake.chat_calls) == 1
            assert await _structure_counts(fixture) == before
        finally:
            await _cleanup_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())
