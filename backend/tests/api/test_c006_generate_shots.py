import asyncio
import os
from uuid import uuid4

import asyncpg
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.services.generate_shots import require_generate_shots_impact_token


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 impact style " + uuid4().hex,
            "雨夜写实",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 impact project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, $2, $3)
            RETURNING id
            """,
            project_id,
            "C006 populated episode",
            "一段待拆解剧本",
        )
        empty_episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 2, $2, $3)
            RETURNING id
            """,
            project_id,
            "C006 empty episode",
            "没有资产的剧本",
        )
        clip_ids = []
        for _ in range(2):
            clip_id = await connection.fetchval(
                """
                INSERT INTO clips (episode_id, requested_duration)
                VALUES ($1, 5)
                RETURNING id
                """,
                episode_id,
            )
            clip_ids.append(clip_id)
        video_ids = []
        for clip_id, suffixes in zip(clip_ids, (("a", "b"), ("c",))):
            for suffix in suffixes:
                video_id = await connection.fetchval(
                    """
                    INSERT INTO clip_videos
                        (clip_id, file_path, sha256, seed, requested_duration)
                    VALUES ($1, $2, $3, $4, 5)
                    RETURNING id
                    """,
                    clip_id,
                    f"projects/{project_id}/clips/{clip_id}/{suffix}.mp4",
                    uuid4().hex,
                    len(video_ids) + 1,
                )
                video_ids.append(video_id)
        slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_name_snapshot, asset_type_snapshot,
                 override_image_path, override_sha256)
            VALUES ($1, 1, '旧人物', 'character', $2, $3)
            RETURNING id
            """,
            clip_ids[0],
            f"projects/{project_id}/clips/{clip_ids[0]}/override.png",
            uuid4().hex,
        )
        return {
            "style_id": style_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "empty_episode_id": empty_episode_id,
            "clip_ids": clip_ids,
            "video_ids": video_ids,
            "slot_id": slot_id,
        }
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        clip_ids = fixture["clip_ids"]
        assert isinstance(clip_ids, list)
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id = ANY($1::int[])",
            clip_ids,
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = ANY($1::int[])",
            clip_ids,
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = ANY($1::int[])", clip_ids
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = ANY($1::int[])",
            [fixture["episode_id"], fixture["empty_episode_id"]],
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


async def _counts(fixture: dict[str, object]) -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        project_id = fixture["project_id"]
        episode_id = fixture["episode_id"]
        return {
            "tasks": await connection.fetchval("SELECT count(*) FROM tasks"),
            "clips": await connection.fetchval(
                "SELECT count(*) FROM clips WHERE episode_id = $1", episode_id
            ),
            "videos": await connection.fetchval(
                """
                SELECT count(*)
                FROM clip_videos
                WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                """,
                episode_id,
            ),
            "slots": await connection.fetchval(
                """
                SELECT count(*)
                FROM clip_ref_slots
                WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                """,
                episode_id,
            ),
            "assets": await connection.fetchval(
                "SELECT count(*) FROM assets WHERE project_id = $1", project_id
            ),
        }
    finally:
        await connection.close()


async def _require_token(episode_id: int, token: str | None):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await require_generate_shots_impact_token(
                session, episode_id, token
            )
    finally:
        await engine.dispose()


async def _bump_clip_revision(clip_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clips SET revision = revision + 1 WHERE id = $1", clip_id
        )
    finally:
        await connection.close()


async def _replace_video(video_id: int, clip_id: int) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM clip_videos WHERE id = $1", video_id)
        return await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration)
            VALUES ($1, $2, $3, 99, 5)
            RETURNING id
            """,
            clip_id,
            "projects/replaced.mp4",
            uuid4().hex,
        )
    finally:
        await connection.close()


async def _change_override(slot_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
            "projects/changed-override.png",
            slot_id,
        )
    finally:
        await connection.close()


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    payload = response.json()
    assert set(payload) == {"detail"}
    assert set(payload["detail"]) == {"code", "message"}
    assert payload["detail"]["code"] == code


def test_generate_shots_impact_token_binds_current_snapshot() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            empty_url = (
                f"/api/episodes/{fixture['empty_episode_id']}"
                "/generate-shots/impact"
            )
            empty = client.post(empty_url, content=b"")
            assert empty.status_code == 200
            assert empty.json() == {
                "clips_count": 0,
                "videos_count": 0,
                "confirm_token": None,
                "expires_in": None,
            }
            assert asyncio.run(_counts(fixture))["tasks"] == 0

            impact_url = (
                f"/api/episodes/{fixture['episode_id']}"
                "/generate-shots/impact"
            )
            before = asyncio.run(_counts(fixture))
            impact = client.post(impact_url, content=b"")
            assert impact.status_code == 200
            impact_payload = impact.json()
            assert set(impact_payload) == {
                "clips_count",
                "videos_count",
                "confirm_token",
                "expires_in",
            }
            assert impact_payload["clips_count"] == 2
            assert impact_payload["videos_count"] == 3
            assert isinstance(impact_payload["confirm_token"], str)
            assert impact_payload["confirm_token"]
            assert impact_payload["expires_in"] == 600
            token = impact_payload["confirm_token"]
            assert asyncio.run(_counts(fixture)) == before
            snapshot = asyncio.run(
                _require_token(fixture["episode_id"], token)
            )
            assert snapshot.clip_revisions == (
                (fixture["clip_ids"][0], 1),
                (fixture["clip_ids"][1], 1),
            )
            assert snapshot.clip_video_ids == tuple(fixture["video_ids"])
            assert len(snapshot.clip_override_media) == 1

            invalid_bodies = (b"{}", b"null", b" \n\t", b"not-json")
            for body in invalid_bodies:
                invalid = client.post(impact_url, content=body)
                _assert_error(invalid, 422, "validation_error")
            assert asyncio.run(_counts(fixture)) == before

            missing = client.post(
                "/api/episodes/999999/generate-shots/impact", content=b""
            )
            _assert_error(missing, 404, "not_found")

            asyncio.run(_bump_clip_revision(fixture["clip_ids"][0]))
            try:
                asyncio.run(_require_token(fixture["episode_id"], token))
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("revision drift accepted by impact token")

            refreshed = client.post(impact_url, content=b"")
            assert refreshed.status_code == 200
            refreshed_token = refreshed.json()["confirm_token"]
            assert isinstance(refreshed_token, str)
            asyncio.run(
                _replace_video(
                    fixture["video_ids"][0], fixture["clip_ids"][0]
                )
            )
            try:
                asyncio.run(
                    _require_token(fixture["episode_id"], refreshed_token)
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("video id drift accepted by impact token")

            latest = client.post(impact_url, content=b"")
            assert latest.status_code == 200
            latest_token = latest.json()["confirm_token"]
            assert isinstance(latest_token, str)
            asyncio.run(_change_override(fixture["slot_id"]))
            try:
                asyncio.run(_require_token(fixture["episode_id"], latest_token))
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("override drift accepted by impact token")

            try:
                asyncio.run(_require_token(fixture["empty_episode_id"], token))
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("cross-episode impact token accepted")
    finally:
        asyncio.run(_cleanup_fixture(fixture))
