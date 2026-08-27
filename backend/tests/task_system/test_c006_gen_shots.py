import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
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


def test_gen_shots_uses_snapshot_prompt_and_dynamic_schema(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        fixture = await _create_fixture()
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.services.gen_shots.async_session_factory", session_factory)
        monkeypatch.setattr("app.tasks.gen_shots.async_session_factory", session_factory)
        task_ids: list[int] = []
        try:
            payload = _build_payload(fixture)
            connection = await asyncpg.connect(_database_url())
            try:
                media_path = await connection.fetchval(
                    "SELECT file_path FROM clip_videos WHERE id = $1",
                    fixture["video_id"],
                )
            finally:
                await connection.close()
            assert isinstance(media_path, str)
            media_file = tmp_path / Path(media_path)
            media_file.parent.mkdir(parents=True, exist_ok=True)
            media_file.write_bytes(b"old clip video")
            snapshot = payload["input_snapshot"]
            assert isinstance(snapshot, dict)
            replacement = snapshot["replacement_snapshot"]
            assert isinstance(replacement, dict)
            clip_media = replacement["clip_media"]
            assert isinstance(clip_media, list)
            assert len(clip_media) == 1
            assert isinstance(clip_media[0], dict)
            clip_media[0]["path"] = media_path
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
            assert await _structure_counts(fixture) == (2, 0, 0, 2)
            assert not media_file.exists()
            assert (tmp_path / "trash" / Path(media_path)).is_file()
            assert app.state.task_handlers["gen_shots"] is gen_shots_handler
        finally:
            connection = await asyncpg.connect(_database_url())
            try:
                await connection.execute(
                    """
                    DELETE FROM clip_shots
                    WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
                await connection.execute(
                    """
                    DELETE FROM clip_ref_slots
                    WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
                await connection.execute(
                    """
                    DELETE FROM clip_videos
                    WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
                await connection.execute(
                    "DELETE FROM clips WHERE episode_id = $1",
                    fixture["episode_id"],
                )
                await connection.execute(
                    """
                    DELETE FROM shot_assets
                    WHERE shot_id IN (SELECT id FROM shots WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
                await connection.execute(
                    "DELETE FROM shots WHERE episode_id = $1",
                    fixture["episode_id"],
                )
            finally:
                await connection.close()
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


async def _create_replace_fixture(data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '替换测试风格')
            RETURNING id
            """,
            "C006 T5 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T5 project " + uuid4().hex,
            style_id,
        )
        target_episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text, script_revision)
            VALUES ($1, 1, '替换目标集', '目标剧本', 4)
            RETURNING id
            """,
            project_id,
        )
        other_episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 2, '保留集', '保留剧本')
            RETURNING id
            """,
            project_id,
        )
        asset_values = [
            ("character", "林夏", "短发，穿蓝色外套"),
            ("scene", "旧车站", "雨夜的空旷站台"),
            ("scene", "河岸", "清晨的河岸"),
        ]
        asset_ids: list[int] = []
        for asset_type, name, description in asset_values:
            asset_id = await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, $2, $3, $4, 'manual')
                RETURNING id
                """,
                project_id,
                asset_type,
                name,
                description,
            )
            asset_ids.append(asset_id)

        target_shot_ids: list[int] = []
        target_shot_rows = [
            (1, 2.5, "中景", "固定", "旧镜头一", "旧台词一", "changed", 4),
            (2, 3.0, "近景", "推", "旧镜头二", "", "normal", 2),
        ]
        for order_index, duration, shot_type, camera, description, dialogue, status, revision in target_shot_rows:
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                target_episode_id,
                order_index,
                duration,
                shot_type,
                camera,
                description,
                dialogue,
                status,
                revision,
            )
            target_shot_ids.append(shot_id)
        await connection.executemany(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            [
                (target_shot_ids[0], asset_ids[0]),
                (target_shot_ids[0], asset_ids[1]),
                (target_shot_ids[1], asset_ids[2]),
            ],
        )

        target_clip_ids: list[int] = []
        for requested_duration, generation_state, freshness, revision in [
            (5, "ready", "stale", 7),
            (6, "empty", "fresh", 3),
        ]:
            clip_id = await connection.fetchval(
                """
                INSERT INTO clips
                    (episode_id, requested_duration, generation_state, freshness, revision)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                target_episode_id,
                requested_duration,
                generation_state,
                freshness,
                revision,
            )
            target_clip_ids.append(clip_id)
        await connection.executemany(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            list(zip(target_clip_ids, target_shot_ids)),
        )

        target_video_ids: list[int] = []
        for clip_id, requested_duration in zip(target_clip_ids, [5, 6]):
            video_id = await connection.fetchval(
                """
                INSERT INTO clip_videos
                    (clip_id, file_path, sha256, seed, requested_duration,
                     actual_duration, is_current, built_prompt)
                VALUES ($1, 'pending', $2, $3, $4, $5, true, '旧视频提示词')
                RETURNING id
                """,
                clip_id,
                uuid4().hex,
                101 + len(target_video_ids),
                requested_duration,
                float(requested_duration) - 0.5,
            )
            target_video_ids.append(video_id)
        target_slot_ids: list[int] = []
        for clip_id, asset_id, asset_name, asset_type in [
            (target_clip_ids[0], asset_ids[0], "林夏", "character"),
            (target_clip_ids[1], asset_ids[2], "河岸", "scene"),
        ]:
            slot_id = await connection.fetchval(
                """
                INSERT INTO clip_ref_slots
                    (clip_id, slot_no, asset_id, asset_name_snapshot,
                     asset_type_snapshot, override_image_path, override_sha256)
                VALUES ($1, 1, $2, $3, $4, 'pending', $5)
                RETURNING id
                """,
                clip_id,
                asset_id,
                asset_name,
                asset_type,
                uuid4().hex,
            )
            target_slot_ids.append(slot_id)

        target_video_paths = [
            f"projects/{project_id}/episodes/{target_episode_id}/clips/{clip_id}/{video_id}.mp4"
            for clip_id, video_id in zip(target_clip_ids, target_video_ids)
        ]
        target_override_paths = [
            f"projects/{project_id}/episodes/{target_episode_id}/clips/{clip_id}/slots/{slot_id}.png"
            for clip_id, slot_id in zip(target_clip_ids, target_slot_ids)
        ]
        await connection.executemany(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
            list(zip(target_video_paths, target_video_ids)),
        )
        await connection.executemany(
            "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
            list(zip(target_override_paths, target_slot_ids)),
        )

        other_shot_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 2.0, '全景', '固定', '保留镜头', '', 'normal', 1)
            RETURNING id
            """,
            other_episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            other_shot_id,
            asset_ids[1],
        )
        other_clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'ready', 'fresh', 5)
            RETURNING id
            """,
            other_episode_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            other_clip_id,
            other_shot_id,
        )
        other_video_id = await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration, is_current)
            VALUES ($1, 'pending', $2, 303, 5, true)
            RETURNING id
            """,
            other_clip_id,
            uuid4().hex,
        )
        other_slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '旧车站', 'scene', 'pending', $3)
            RETURNING id
            """,
            other_clip_id,
            asset_ids[1],
            uuid4().hex,
        )
        other_video_path = (
            f"projects/{project_id}/episodes/{other_episode_id}/clips/"
            f"{other_clip_id}/{other_video_id}.mp4"
        )
        other_override_path = (
            f"projects/{project_id}/episodes/{other_episode_id}/clips/"
            f"{other_clip_id}/slots/{other_slot_id}.png"
        )
        await connection.execute(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
            other_video_path,
            other_video_id,
        )
        await connection.execute(
            "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
            other_override_path,
            other_slot_id,
        )
    finally:
        await connection.close()

    target_media = [
        *[
            {"kind": "clip_video", "id": video_id, "path": path}
            for video_id, path in zip(target_video_ids, target_video_paths)
        ],
        *[
            {"kind": "slot_override", "id": slot_id, "path": path}
            for slot_id, path in zip(target_slot_ids, target_override_paths)
        ],
    ]
    target_media.sort(key=lambda item: (item["kind"] != "clip_video", item["id"]))
    other_media = [
        {"kind": "clip_video", "id": other_video_id, "path": other_video_path},
        {"kind": "slot_override", "id": other_slot_id, "path": other_override_path},
    ]
    for media in [*target_media, *other_media]:
        media_file = data_dir / Path(media["path"])
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(f"media-{media['id']}".encode())

    return {
        "style_id": style_id,
        "project_id": project_id,
        "target_episode_id": target_episode_id,
        "other_episode_id": other_episode_id,
        "script_revision": 4,
        "asset_ids": asset_ids,
        "assets": [
            {
                "id": asset_id,
                "type": asset_type,
                "name": name,
                "description": description,
            }
            for asset_id, (asset_type, name, description) in zip(asset_ids, asset_values)
        ],
        "target_shot_ids": target_shot_ids,
        "target_clip_ids": target_clip_ids,
        "target_video_ids": sorted(target_video_ids),
        "target_media": target_media,
        "other_media": other_media,
        "target_shot_snapshot": [
            {"id": shot_id, "revision": revision}
            for shot_id, (_, _, _, _, _, _, _, revision) in zip(
                target_shot_ids, target_shot_rows
            )
        ],
        "target_clip_snapshot": [
            {"id": clip_id, "revision": revision}
            for clip_id, revision in zip(target_clip_ids, [7, 3])
        ],
        "other_shot_id": other_shot_id,
        "other_clip_id": other_clip_id,
        "other_video_id": other_video_id,
        "other_slot_id": other_slot_id,
        "data_dir": data_dir,
    }


async def _cleanup_replace_fixture(
    fixture: dict[str, object], task_ids: list[int]
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        episode_ids = [fixture["target_episode_id"], fixture["other_episode_id"]]
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id IN (SELECT id FROM shots WHERE episode_id = ANY($1::int[]))",
            episode_ids,
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = ANY($1::int[]))",
            episode_ids,
        )
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = ANY($1::int[]))",
            episode_ids,
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = ANY($1::int[]))",
            episode_ids,
        )
        await connection.execute(
            "DELETE FROM clips WHERE episode_id = ANY($1::int[])", episode_ids
        )
        await connection.execute(
            "DELETE FROM shots WHERE episode_id = ANY($1::int[])", episode_ids
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = ANY($1::int[])", episode_ids
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()

    data_dir = fixture["data_dir"]
    assert isinstance(data_dir, Path)
    for media in [*fixture["target_media"], *fixture["other_media"]]:
        path = Path(media["path"])
        for media_file in [data_dir / path, data_dir / "trash" / path]:
            if media_file.is_file():
                media_file.unlink()


def _replace_payload(
    fixture: dict[str, object],
    replacement: dict[str, object] | None = None,
) -> dict[str, object]:
    if replacement is None:
        replacement = {
            "shots": [dict(row) for row in fixture["target_shot_snapshot"]],
            "clips": [dict(row) for row in fixture["target_clip_snapshot"]],
            "clip_video_ids": list(fixture["target_video_ids"]),
            "clip_media": [dict(item) for item in fixture["target_media"]],
        }
    snapshot = {
        "episode_id": fixture["target_episode_id"],
        "project_id": fixture["project_id"],
        "script": "目标剧本",
        "script_revision": fixture["script_revision"],
        "style": "替换测试风格",
        "template_key": "script2shots",
        "template_content": "模板",
        "assets": [dict(asset) for asset in fixture["assets"]],
        "rendered_prompt": "T5 入队后的完整分镜 prompt",
        "model": "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit",
        "temperature": 0.2,
        "guided_json_schema": build_generate_shots_response_format(
            list(fixture["asset_ids"])
        ),
        "replacement_snapshot": replacement,
    }
    return {
        "input_snapshot": snapshot,
        "input_hash": None,
        "source_revisions": {
            "episode": {
                "id": fixture["target_episode_id"],
                "script_revision": fixture["script_revision"],
            },
            "assets": [
                {"id": asset["id"], "revision": 1}
                for asset in fixture["assets"]
            ],
            "shots": [dict(row) for row in fixture["target_shot_snapshot"]],
            "clips": [dict(row) for row in fixture["target_clip_snapshot"]],
        },
    }


async def _read_episode_structure(
    connection: asyncpg.Connection, episode_id: int
) -> dict[str, object]:
    shots = await connection.fetch(
        """
        SELECT id, order_index, duration_est, shot_type, camera, description,
               dialogue, status, revision
        FROM shots WHERE episode_id = $1 ORDER BY id
        """,
        episode_id,
    )
    clips = await connection.fetch(
        """
        SELECT id, generation_mode, user_note, requested_duration, prompt_cache,
               prompt_input_hash, generation_state, freshness, revision
        FROM clips WHERE episode_id = $1 ORDER BY id
        """,
        episode_id,
    )
    clip_ids = [row["id"] for row in clips]
    shot_ids = [row["id"] for row in shots]
    shot_assets = (
        await connection.fetch(
            """
            SELECT shot_id, asset_id FROM shot_assets
            WHERE shot_id = ANY($1::int[]) ORDER BY shot_id, asset_id
            """,
            shot_ids,
        )
        if shot_ids
        else []
    )
    clip_shots = (
        await connection.fetch(
            """
            SELECT clip_id, shot_id, position FROM clip_shots
            WHERE clip_id = ANY($1::int[]) ORDER BY clip_id, position
            """,
            clip_ids,
        )
        if clip_ids
        else []
    )
    clip_videos = (
        await connection.fetch(
            """
            SELECT id, clip_id, file_path, sha256, seed, requested_duration,
                   actual_duration, is_current, built_prompt, input_hash, input_snapshot
            FROM clip_videos WHERE clip_id = ANY($1::int[]) ORDER BY id
            """,
            clip_ids,
        )
        if clip_ids
        else []
    )
    clip_ref_slots = (
        await connection.fetch(
            """
            SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot,
                   asset_type_snapshot, override_image_path, override_sha256, enabled
            FROM clip_ref_slots WHERE clip_id = ANY($1::int[]) ORDER BY id
            """,
            clip_ids,
        )
        if clip_ids
        else []
    )
    marker = await connection.fetchval(
        "SELECT shots_generated_script_revision FROM episodes WHERE id = $1",
        episode_id,
    )
    return {
        "shots": [dict(row) for row in shots],
        "shot_assets": [dict(row) for row in shot_assets],
        "clips": [dict(row) for row in clips],
        "clip_shots": [dict(row) for row in clip_shots],
        "clip_videos": [dict(row) for row in clip_videos],
        "clip_ref_slots": [dict(row) for row in clip_ref_slots],
        "marker": marker,
    }


async def _read_replace_structure(
    fixture: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        return (
            await _read_episode_structure(connection, fixture["target_episode_id"]),
            await _read_episode_structure(connection, fixture["other_episode_id"]),
        )
    finally:
        await connection.close()


class _CommitFailureSession(AsyncSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sync_session.info["c006_t5_fail_commit"] = True


def test_gen_shots_success_replaces_episode_and_trashes_clip_media(
    monkeypatch, tmp_path
) -> None:
    async def run() -> None:
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.services.gen_shots.async_session_factory", session_factory)
        monkeypatch.setattr("app.tasks.gen_shots.async_session_factory", session_factory)
        fake_holder: dict[str, _FakeVLLM | None] = {"value": None}
        monkeypatch.setattr(
            "app.tasks.gen_shots.VLLMClient",
            lambda base_url: fake_holder["value"],
        )

        def fail_before_commit(sync_session: Session) -> None:
            if sync_session.info.get("c006_t5_fail_commit"):
                raise RuntimeError("simulated database commit failure")

        event.listen(Session, "before_commit", fail_before_commit)
        fixtures: list[dict[str, object]] = []
        task_ids: list[int] = []
        try:
            fixture = await _create_replace_fixture(tmp_path)
            fixtures.append(fixture)
            before_target, before_other = await _read_replace_structure(fixture)
            output = {
                "shots": [
                    {
                        "order": 1,
                        "duration_est": 3.0,
                        "shot_type": "远景",
                        "camera": "推",
                        "description": "林夏走到旧车站边缘，雨水从蓝色外套上滑落",
                        "dialogue": "林夏:我到了",
                        "asset_ids": [fixture["asset_ids"][0], fixture["asset_ids"][1]],
                    },
                    {
                        "order": 2,
                        "duration_est": 1.5,
                        "shot_type": "特写",
                        "camera": "固定",
                        "description": "镜头贴近林夏的眼睛，冷光映出她抬眼的动作",
                        "dialogue": "",
                        "asset_ids": [fixture["asset_ids"][0]],
                    },
                ]
            }
            fake = _FakeVLLM(_response(output))
            fake_holder["value"] = fake
            task_id = await _insert_task(
                _replace_payload(fixture), fixture["target_episode_id"], session_factory
            )
            task_ids.append(task_id)
            await _run_task(task_id, session_factory)
            status, error_msg = await _read_task(task_id, session_factory)
            assert status == "done"
            assert error_msg is None
            assert fake.wake_calls == 1
            assert len(fake.chat_calls) == 1
            target_state, other_state = await _read_replace_structure(fixture)
            assert target_state["clips"] == []
            assert target_state["clip_shots"] == []
            assert target_state["clip_videos"] == []
            assert target_state["clip_ref_slots"] == []
            assert target_state["marker"] == fixture["script_revision"]
            new_shots = target_state["shots"]
            assert len(new_shots) == 2
            assert [row["order_index"] for row in new_shots] == [1, 2]
            assert [row["duration_est"] for row in new_shots] == [3.0, 1.5]
            assert [row["shot_type"] for row in new_shots] == ["远景", "特写"]
            assert [row["camera"] for row in new_shots] == ["推", "固定"]
            assert [row["status"] for row in new_shots] == ["normal", "normal"]
            assert [row["revision"] for row in new_shots] == [1, 1]
            assert [row["description"] for row in new_shots] == [
                output["shots"][0]["description"],
                output["shots"][1]["description"],
            ]
            assert target_state["shot_assets"] == [
                {"shot_id": new_shots[0]["id"], "asset_id": fixture["asset_ids"][0]},
                {"shot_id": new_shots[0]["id"], "asset_id": fixture["asset_ids"][1]},
                {"shot_id": new_shots[1]["id"], "asset_id": fixture["asset_ids"][0]},
            ]
            assert other_state == before_other
            assert before_target["shots"]
            assert {row["id"] for row in new_shots}.isdisjoint(
                {row["id"] for row in before_target["shots"]}
            )
            for media in fixture["target_media"]:
                media_path = Path(media["path"])
                assert not (tmp_path / media_path).exists()
                assert (tmp_path / "trash" / media_path).is_file()
            for media in fixture["other_media"]:
                media_path = Path(media["path"])
                assert (tmp_path / media_path).is_file()
                assert not (tmp_path / "trash" / media_path).exists()

            empty_replacement = {
                "shots": [
                    {"id": row["id"], "revision": row["revision"]}
                    for row in target_state["shots"]
                ],
                "clips": [],
                "clip_video_ids": [],
                "clip_media": [],
            }
            empty_fake = _FakeVLLM(_response({"shots": []}))
            fake_holder["value"] = empty_fake
            empty_task_id = await _insert_task(
                _replace_payload(fixture, empty_replacement),
                fixture["target_episode_id"],
                session_factory,
            )
            task_ids.append(empty_task_id)
            await _run_task(empty_task_id, session_factory)
            empty_status, empty_error = await _read_task(
                empty_task_id, session_factory
            )
            assert empty_status == "done"
            assert empty_error is None
            assert empty_fake.wake_calls == 1
            assert len(empty_fake.chat_calls) == 1
            empty_target, empty_other = await _read_replace_structure(fixture)
            assert empty_target["shots"] == []
            assert empty_target["shot_assets"] == []
            assert empty_target["clips"] == []
            assert empty_target["marker"] == fixture["script_revision"]
            assert empty_other == before_other

            commit_fixture = await _create_replace_fixture(tmp_path)
            fixtures.append(commit_fixture)
            commit_before, commit_other_before = await _read_replace_structure(
                commit_fixture
            )
            commit_fake = _FakeVLLM(
                _response({"shots": [_shot(asset_ids=[commit_fixture["asset_ids"][0]])]})
            )
            fake_holder["value"] = commit_fake
            failing_factory = async_sessionmaker(
                engine,
                class_=_CommitFailureSession,
                expire_on_commit=False,
            )
            monkeypatch.setattr(
                "app.tasks.gen_shots.async_session_factory", failing_factory
            )
            commit_task_id = await _insert_task(
                _replace_payload(commit_fixture),
                commit_fixture["target_episode_id"],
                session_factory,
            )
            task_ids.append(commit_task_id)
            await _run_task(commit_task_id, session_factory)
            commit_status, commit_error = await _read_task(
                commit_task_id, session_factory
            )
            assert commit_status == "failed"
            assert commit_error is not None
            assert "simulated database commit failure" in commit_error
            commit_after, commit_other_after = await _read_replace_structure(
                commit_fixture
            )
            assert commit_after == commit_before
            assert commit_other_after == commit_other_before
            for media in commit_fixture["target_media"]:
                media_path = Path(media["path"])
                assert (tmp_path / media_path).is_file()
                assert not (tmp_path / "trash" / media_path).exists()

            restore_fixture = await _create_replace_fixture(tmp_path)
            fixtures.append(restore_fixture)
            restore_before, restore_other_before = await _read_replace_structure(
                restore_fixture
            )
            restore_fake = _FakeVLLM(
                _response({"shots": [_shot(asset_ids=[restore_fixture["asset_ids"][0]])]})
            )
            fake_holder["value"] = restore_fake
            monkeypatch.setattr(
                "app.tasks.gen_shots.async_session_factory", failing_factory
            )

            def fail_restore(_moved) -> None:
                raise OSError("simulated restore failure")

            monkeypatch.setattr("app.tasks.gen_shots._restore_media", fail_restore)
            restore_task_id = await _insert_task(
                _replace_payload(restore_fixture),
                restore_fixture["target_episode_id"],
                session_factory,
            )
            task_ids.append(restore_task_id)
            await _run_task(restore_task_id, session_factory)
            restore_status, restore_error = await _read_task(
                restore_task_id, session_factory
            )
            assert restore_status == "failed"
            assert restore_error is not None
            assert "trash restore failed" in restore_error
            assert "simulated restore failure" in restore_error
            restore_after, restore_other_after = await _read_replace_structure(
                restore_fixture
            )
            assert restore_after == restore_before
            assert restore_other_after == restore_other_before
            for media in restore_fixture["target_media"]:
                media_path = Path(media["path"])
                assert not (tmp_path / media_path).exists()
                assert (tmp_path / "trash" / media_path).is_file()
        finally:
            monkeypatch.setattr("app.tasks.gen_shots.async_session_factory", session_factory)
            for fixture in reversed(fixtures):
                await _cleanup_replace_fixture(fixture, task_ids)
            event.remove(Session, "before_commit", fail_before_commit)
            await engine.dispose()

    asyncio.run(run())


class _FailureVLLM:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.wake_calls = 0
        self.chat_calls: list[dict[str, object]] = []

    async def wake(self) -> None:
        self.wake_calls += 1
        if self.stage == "wake":
            raise RuntimeError("simulated wake failure")

    async def structured_chat(self, **request: object) -> dict[str, object]:
        self.chat_calls.append(request)
        if self.stage == "chat":
            raise RuntimeError("simulated vLLM HTTP 503")
        raise AssertionError("structured_chat was not expected for this failure")


async def _mutate_database(statement: str, *arguments: object) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(statement, *arguments)
    finally:
        await connection.close()


def test_gen_shots_failures_preserve_existing_structure(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.services.gen_shots.async_session_factory", session_factory)
        monkeypatch.setattr("app.tasks.gen_shots.async_session_factory", session_factory)
        fake_holder: dict[str, object] = {"value": None}
        monkeypatch.setattr(
            "app.tasks.gen_shots.VLLMClient",
            lambda base_url: fake_holder["value"],
        )

        async def failure_case(
            fake: object,
            expected_error: str,
            *,
            mutate: Callable[[dict[str, object]], Awaitable[None]] | None = None,
            missing_last_file: bool = False,
        ) -> None:
            fixture = await _create_replace_fixture(tmp_path)
            task_ids: list[int] = []
            try:
                payload = _replace_payload(fixture)
                if mutate is not None:
                    await mutate(fixture)
                before_target, before_other = await _read_replace_structure(fixture)
                if missing_last_file:
                    last_media = fixture["target_media"][-1]
                    (tmp_path / Path(last_media["path"])).unlink()
                fake_holder["value"] = fake
                task_id = await _insert_task(
                    payload, fixture["target_episode_id"], session_factory
                )
                task_ids.append(task_id)
                await _run_task(task_id, session_factory)
                status, error_msg = await _read_task(task_id, session_factory)
                assert status == "failed"
                assert error_msg is not None
                assert expected_error in error_msg
                after_target, after_other = await _read_replace_structure(fixture)
                assert after_target == before_target
                assert after_other == before_other
                if hasattr(fake, "wake_calls"):
                    assert fake.wake_calls == 1
                if hasattr(fake, "chat_calls"):
                    assert len(fake.chat_calls) == (0 if getattr(fake, "stage", None) == "wake" else 1)
                for media in fixture["target_media"]:
                    media_path = Path(media["path"])
                    source = tmp_path / media_path
                    trash = tmp_path / "trash" / media_path
                    if missing_last_file and media is fixture["target_media"][-1]:
                        assert not source.exists()
                    else:
                        assert source.is_file()
                    assert not trash.exists()
                assert app.state.task_handlers["gen_shots"] is gen_shots_handler
            finally:
                await _cleanup_replace_fixture(fixture, task_ids)

        try:
            await failure_case(_FailureVLLM("wake"), "simulated wake failure")
            await failure_case(_FailureVLLM("chat"), "simulated vLLM HTTP 503")
            await failure_case(
                _FakeVLLM(_response("not valid json")),
                "vLLM response is not a valid script2shots JSON object",
            )

            deleted_asset_fixture = await _create_replace_fixture(tmp_path)
            deleted_asset_tasks: list[int] = []
            try:
                deleted_asset_id = deleted_asset_fixture["asset_ids"][0]
                await _mutate_database(
                    "DELETE FROM assets WHERE id = $1", deleted_asset_id
                )
                before_target, before_other = await _read_replace_structure(
                    deleted_asset_fixture
                )
                fake = _FakeVLLM(
                    _response(
                        {
                            "shots": [
                                _shot(asset_ids=[deleted_asset_id]),
                            ]
                        }
                    )
                )
                fake_holder["value"] = fake
                task_id = await _insert_task(
                    _replace_payload(deleted_asset_fixture),
                    deleted_asset_fixture["target_episode_id"],
                    session_factory,
                )
                deleted_asset_tasks.append(task_id)
                await _run_task(task_id, session_factory)
                status, error_msg = await _read_task(task_id, session_factory)
                assert status == "failed"
                assert error_msg is not None
                assert "no longer valid for the project" in error_msg
                assert fake.wake_calls == 1
                assert len(fake.chat_calls) == 1
                after_target, after_other = await _read_replace_structure(
                    deleted_asset_fixture
                )
                assert after_target == before_target
                assert after_other == before_other
            finally:
                await _cleanup_replace_fixture(
                    deleted_asset_fixture, deleted_asset_tasks
                )

            snapshot_row = await _create_replace_fixture(tmp_path)
            snapshot_tasks: list[int] = []
            try:
                await _mutate_database(
                    "UPDATE shots SET revision = revision + 1 WHERE id = $1",
                    snapshot_row["target_shot_ids"][0],
                )
                before_target, before_other = await _read_replace_structure(snapshot_row)
                fake = _FakeVLLM(
                    _response({"shots": [_shot(asset_ids=[snapshot_row["asset_ids"][0]])]})
                )
                fake_holder["value"] = fake
                task_id = await _insert_task(
                    _replace_payload(snapshot_row),
                    snapshot_row["target_episode_id"],
                    session_factory,
                )
                snapshot_tasks.append(task_id)
                await _run_task(task_id, session_factory)
                status, error_msg = await _read_task(task_id, session_factory)
                assert status == "failed"
                assert error_msg is not None
                assert "replacement snapshot shots changed" in error_msg
                assert fake.wake_calls == 1
                assert len(fake.chat_calls) == 1
                after_target, after_other = await _read_replace_structure(snapshot_row)
                assert after_target == before_target
                assert after_other == before_other
            finally:
                await _cleanup_replace_fixture(snapshot_row, snapshot_tasks)

            async def change_clip_revision(fixture: dict[str, object]) -> None:
                await _mutate_database(
                    "UPDATE clips SET revision = revision + 1 WHERE id = $1",
                    fixture["target_clip_ids"][0],
                )

            await failure_case(
                _FakeVLLM(
                    _response(
                        {
                            "shots": [
                                _shot(asset_ids=[]),
                            ]
                        }
                    )
                ),
                "replacement snapshot clips changed",
                mutate=change_clip_revision,
            )

            async def change_media_owner(fixture: dict[str, object]) -> None:
                await _mutate_database(
                    """
                    UPDATE clip_videos
                    SET clip_id = $2, is_current = false
                    WHERE id = $1
                    """,
                    fixture["target_video_ids"][0],
                    fixture["other_clip_id"],
                )

            await failure_case(
                _FakeVLLM(_response({"shots": [_shot(asset_ids=[])]})),
                "replacement snapshot clip videos changed",
                mutate=change_media_owner,
            )

            async def change_media_path(fixture: dict[str, object]) -> None:
                media_path = fixture["target_media"][0]["path"]
                await _mutate_database(
                    "UPDATE clip_videos SET file_path = $2 WHERE id = $1",
                    fixture["target_video_ids"][0],
                    f"{media_path}.changed",
                )

            await failure_case(
                _FakeVLLM(_response({"shots": [_shot(asset_ids=[])]})),
                "replacement snapshot clip video changed",
                mutate=change_media_path,
            )

            await failure_case(
                _FakeVLLM(_response({"shots": [_shot(asset_ids=[])]})),
                "FileNotFoundError",
                missing_last_file=True,
            )
        finally:
            await engine.dispose()

    asyncio.run(run())
