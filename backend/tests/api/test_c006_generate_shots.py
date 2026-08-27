import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
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


async def _create_generate_fixture(*, with_assets: bool) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 generate style " + uuid4().hex,
            "冷峻写实",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 generate project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, $2, $3)
            RETURNING id
            """,
            project_id,
            "C006 generate episode",
            "剧本 {{style}}",
        )
        asset_ids: list[int] = []
        valid_asset_ids: list[int] = []
        if with_assets:
            for asset_type, name, description in (
                ("character", "林夏", "短发，穿蓝色外套"),
                ("scene", "旧车站", "雨夜的空旷站台"),
                ("prop", "旧伞", "一把黑色雨伞"),
            ):
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
                if asset_type != "prop":
                    valid_asset_ids.append(asset_id)

        shot_ids: list[int] = []
        shot_snapshot: list[dict[str, int]] = []
        clip_ids: list[int] = []
        clip_snapshot: list[dict[str, int]] = []
        video_media: list[dict[str, object]] = []
        override_media: list[dict[str, object]] = []
        if with_assets:
            for order, revision in ((1, 2), (2, 1)):
                shot_id = await connection.fetchval(
                    """
                    INSERT INTO shots
                        (episode_id, order_index, duration_est, shot_type,
                         camera, description, dialogue, status, revision)
                    VALUES ($1, $2, 2.5, '近景', '固定', $3, '', 'changed', $4)
                    RETURNING id
                    """,
                    episode_id,
                    order,
                    f"旧镜头 {order}",
                    revision,
                )
                shot_ids.append(shot_id)
                shot_snapshot.append({"id": shot_id, "revision": revision})

            for video_count in (2, 1):
                clip_id = await connection.fetchval(
                    """
                    INSERT INTO clips (episode_id, requested_duration)
                    VALUES ($1, 5)
                    RETURNING id
                    """,
                    episode_id,
                )
                clip_ids.append(clip_id)
                clip_snapshot.append({"id": clip_id, "revision": 1})
                for video_no in range(1, video_count + 1):
                    path = (
                        f"projects/{project_id}/episodes/{episode_id}/"
                        f"clips/{clip_id}/{video_no}.mp4"
                    )
                    video_id = await connection.fetchval(
                        """
                        INSERT INTO clip_videos
                            (clip_id, file_path, sha256, seed, requested_duration)
                        VALUES ($1, $2, $3, $4, 5)
                        RETURNING id
                        """,
                        clip_id,
                        path,
                        uuid4().hex,
                        video_no,
                    )
                    video_media.append(
                        {"kind": "clip_video", "id": video_id, "path": path}
                    )
                for slot_no, override_path in (
                    (1, f"projects/{project_id}/episodes/{episode_id}/clips/{clip_id}/slots/{clip_id}.png"),
                    (2, None),
                ):
                    slot_id = await connection.fetchval(
                        """
                        INSERT INTO clip_ref_slots
                            (clip_id, slot_no, asset_id, asset_name_snapshot,
                             asset_type_snapshot, override_image_path,
                             override_sha256)
                        VALUES ($1, $2, $3, '林夏', 'character', $4, $5)
                        RETURNING id
                        """,
                        clip_id,
                        slot_no,
                        valid_asset_ids[0] if valid_asset_ids else None,
                        override_path,
                        uuid4().hex if override_path is not None else None,
                    )
                    if override_path is not None:
                        override_media.append(
                            {
                                "kind": "slot_override",
                                "id": slot_id,
                                "path": override_path,
                            }
                        )
        return {
            "style_id": style_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "asset_ids": asset_ids,
            "valid_asset_ids": valid_asset_ids,
            "shot_ids": shot_ids,
            "shot_snapshot": shot_snapshot,
            "clip_ids": clip_ids,
            "clip_snapshot": clip_snapshot,
            "video_media": video_media,
            "override_media": override_media,
        }
    finally:
        await connection.close()


async def _cleanup_generate_fixture(
    fixture: dict[str, object], task_ids: list[int] | None = None
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        clip_ids = fixture["clip_ids"]
        shot_ids = fixture["shot_ids"]
        asset_ids = fixture["asset_ids"]
        assert isinstance(clip_ids, list)
        assert isinstance(shot_ids, list)
        assert isinstance(asset_ids, list)
        if clip_ids:
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
        if shot_ids:
            await connection.execute(
                "DELETE FROM shot_assets WHERE shot_id = ANY($1::int[])",
                shot_ids,
            )
            await connection.execute(
                "DELETE FROM shots WHERE id = ANY($1::int[])", shot_ids
            )
        if asset_ids:
            await connection.execute(
                "DELETE FROM assets WHERE id = ANY($1::int[])", asset_ids
            )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


async def _read_script2shots_template() -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        content = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'script2shots'"
        )
        assert isinstance(content, str)
        return content
    finally:
        await connection.close()


async def _write_script2shots_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'script2shots'",
            content,
        )
    finally:
        await connection.close()


async def _read_task(task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT type, target_id, request_id, status, progress, payload
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )
        assert row is not None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert isinstance(payload, dict)
        return {
            "type": row["type"],
            "target_id": row["target_id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "progress": row["progress"],
            "payload": payload,
        }
    finally:
        await connection.close()


async def _task_count() -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        return await connection.fetchval("SELECT count(*) FROM tasks")
    finally:
        await connection.close()


async def _active_generate_tasks(episode_id: int) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(_database_url())
    try:
        return await connection.fetch(
            """
            SELECT id, type, target_id, request_id, status, progress
            FROM tasks
            WHERE type = 'gen_shots' AND target_id = $1
              AND status IN ('queued', 'running')
            ORDER BY id
            """,
            episode_id,
        )
    finally:
        await connection.close()


async def _mark_generate_task_done(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE tasks
            SET status = 'done', progress = 1, finished_at = now()
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()


def _assert_no_unique_items(value: object) -> None:
    if isinstance(value, dict):
        assert "uniqueItems" not in value
        for nested in value.values():
            _assert_no_unique_items(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_unique_items(nested)


def test_generate_shots_requires_assets() -> None:
    fixture = asyncio.run(_create_generate_fixture(with_assets=False))
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            before = asyncio.run(_task_count())
            impact = client.post(
                f"/api/episodes/{fixture['episode_id']}/generate-shots/impact",
                content=b"",
            )
            assert impact.status_code == 200
            assert impact.json() == {
                "clips_count": 0,
                "videos_count": 0,
                "confirm_token": None,
                "expires_in": None,
            }
            response = client.post(
                f"/api/episodes/{fixture['episode_id']}/generate-shots",
                json={},
            )
            _assert_error(response, 409, "conflict")
            assert asyncio.run(_task_count()) == before
    finally:
        asyncio.run(_cleanup_generate_fixture(fixture))


def test_generate_shots_enqueues_exact_snapshot_and_dynamic_schema() -> None:
    original_template = asyncio.run(_read_script2shots_template())
    template = "prefix={{assets}}|style={{style}}|script={{script}}|suffix"
    asyncio.run(_write_script2shots_template(template))
    fixture = asyncio.run(_create_generate_fixture(with_assets=True))
    task_ids: list[int] = []
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            url = f"/api/episodes/{fixture['episode_id']}/generate-shots"
            for body in (
                None,
                b"null",
                b"[]",
                b'{"request_id":"not-allowed"}',
                b'{"confirm_token":17}',
                b'{"confirm_token":""}',
                b'{"confirm_token":"   "}',
            ):
                kwargs: dict[str, object] = {}
                if body is not None:
                    kwargs["content"] = body
                    kwargs["headers"] = {"content-type": "application/json"}
                invalid = client.post(url, **kwargs)
                _assert_error(invalid, 422, "validation_error")

            missing = client.post(url, json={})
            _assert_error(missing, 409, "conflict")
            impact = client.post(
                f"{url}/impact",
                content=b"",
            )
            assert impact.status_code == 200
            token = impact.json()["confirm_token"]
            assert isinstance(token, str) and token
            valid = client.post(url, json={"confirm_token": token})
            assert valid.status_code == 202
            assert valid.json().keys() == {"task_id"}
            task_id = valid.json()["task_id"]
            assert isinstance(task_id, int) and task_id > 0
            task_ids.append(task_id)

            task = asyncio.run(_read_task(task_id))
            assert task["type"] == "gen_shots"
            assert task["target_id"] == fixture["episode_id"]
            assert task["request_id"] is None
            assert task["status"] == "queued"
            assert task["progress"] == 0
            payload = task["payload"]
            assert isinstance(payload, dict)
            assert set(payload) == {
                "input_snapshot",
                "input_hash",
                "source_revisions",
            }
            assert payload["input_hash"] is None

            snapshot = payload["input_snapshot"]
            assert isinstance(snapshot, dict)
            assert set(snapshot) == {
                "episode_id",
                "project_id",
                "script",
                "script_revision",
                "style",
                "template_key",
                "template_content",
                "assets",
                "rendered_prompt",
                "model",
                "temperature",
                "guided_json_schema",
                "replacement_snapshot",
            }
            assert snapshot["episode_id"] == fixture["episode_id"]
            assert snapshot["project_id"] == fixture["project_id"]
            assert snapshot["script"] == "剧本 {{style}}"
            assert snapshot["script_revision"] == 1
            assert snapshot["style"] == "冷峻写实"
            assert snapshot["template_key"] == "script2shots"
            assert snapshot["template_content"] == template
            expected_assets = [
                {
                    "id": fixture["valid_asset_ids"][0],
                    "type": "character",
                    "name": "林夏",
                    "description": "短发，穿蓝色外套",
                },
                {
                    "id": fixture["valid_asset_ids"][1],
                    "type": "scene",
                    "name": "旧车站",
                    "description": "雨夜的空旷站台",
                },
            ]
            assert snapshot["assets"] == expected_assets
            assert snapshot["rendered_prompt"] == (
                'prefix=[{"id":%d,"type":"character","name":"林夏",'
                '"description":"短发，穿蓝色外套"},{"id":%d,"type":"scene",'
                '"name":"旧车站","description":"雨夜的空旷站台"}]|'
                "style=冷峻写实|script=剧本 {{style}}|suffix"
                % tuple(fixture["valid_asset_ids"])
            )
            assert snapshot["model"] == "Qwen3-30B-A3B-Instruct-2507-AWQ-4bit"
            assert snapshot["temperature"] == 0.2

            schema = snapshot["guided_json_schema"]
            assert isinstance(schema, dict)
            _assert_no_unique_items(schema)
            assert schema["type"] == "json_schema"
            assert schema["json_schema"]["name"] == "script2shots"
            assert schema["json_schema"]["strict"] is True
            inner = schema["json_schema"]["schema"]
            assert set(inner) == {
                "type",
                "properties",
                "required",
                "additionalProperties",
            }
            assert inner["type"] == "object"
            assert inner["required"] == ["shots"]
            assert inner["additionalProperties"] is False
            shots_schema = inner["properties"]["shots"]
            assert set(shots_schema) == {"type", "items"}
            item_schema = shots_schema["items"]
            assert set(item_schema["properties"]) == {
                "order",
                "duration_est",
                "shot_type",
                "camera",
                "description",
                "dialogue",
                "asset_ids",
            }
            assert item_schema["required"] == [
                "order",
                "duration_est",
                "shot_type",
                "camera",
                "description",
                "dialogue",
                "asset_ids",
            ]
            assert item_schema["additionalProperties"] is False
            assert item_schema["properties"]["duration_est"] == {
                "type": "number",
                "minimum": 1,
                "maximum": 5,
            }
            assert item_schema["properties"]["shot_type"]["enum"] == [
                "远景",
                "全景",
                "中景",
                "近景",
                "特写",
            ]
            assert item_schema["properties"]["camera"]["enum"] == [
                "固定",
                "推",
                "拉",
                "摇",
                "移",
                "跟",
                "手持",
            ]
            assert item_schema["properties"]["asset_ids"]["items"]["enum"] == fixture["valid_asset_ids"]
            assert "minItems" not in shots_schema

            replacement = snapshot["replacement_snapshot"]
            assert replacement == {
                "shots": fixture["shot_snapshot"],
                "clips": fixture["clip_snapshot"],
                "clip_video_ids": [
                    item["id"] for item in fixture["video_media"]
                ],
                "clip_media": fixture["video_media"] + fixture["override_media"],
            }
            assert set(replacement) == {
                "shots",
                "clips",
                "clip_video_ids",
                "clip_media",
            }
            media = replacement["clip_media"]
            assert all(set(item) == {"kind", "id", "path"} for item in media)
            video_items = [item for item in media if item["kind"] == "clip_video"]
            override_items = [
                item for item in media if item["kind"] == "slot_override"
            ]
            assert media == video_items + override_items
            assert [item["id"] for item in video_items] == sorted(
                item["id"] for item in video_items
            )
            assert [item["id"] for item in override_items] == sorted(
                item["id"] for item in override_items
            )
            assert replacement["clip_video_ids"] == [
                item["id"] for item in video_items
            ]
            revisions = payload["source_revisions"]
            assert revisions == {
                "episode": {
                    "id": fixture["episode_id"],
                    "script_revision": 1,
                },
                "assets": [
                    {"id": asset_id, "revision": 1}
                    for asset_id in fixture["valid_asset_ids"]
                ],
                "shots": fixture["shot_snapshot"],
                "clips": fixture["clip_snapshot"],
            }
    finally:
        asyncio.run(_write_script2shots_template(original_template))
        asyncio.run(_cleanup_generate_fixture(fixture, task_ids))


def test_generate_shots_active_conflict() -> None:
    original_template = asyncio.run(_read_script2shots_template())
    asyncio.run(
        _write_script2shots_template(
            "assets={{assets}}|style={{style}}|script={{script}}"
        )
    )
    fixture = asyncio.run(_create_generate_fixture(with_assets=True))
    task_ids: list[int] = []
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            url = f"/api/episodes/{fixture['episode_id']}/generate-shots"
            impact = client.post(f"{url}/impact", content=b"")
            assert impact.status_code == 200
            token = impact.json()["confirm_token"]
            assert isinstance(token, str) and token

            def submit() -> object:
                return client.post(url, json={"confirm_token": token})

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: submit(), (1, 2)))
            assert sorted(response.status_code for response in responses) == [202, 409]
            for response in responses:
                if response.status_code == 202:
                    task_ids.append(response.json()["task_id"])
                else:
                    _assert_error(response, 409, "conflict")
            assert len(task_ids) == 1
            active = asyncio.run(_active_generate_tasks(fixture["episode_id"]))
            assert len(active) == 1
            assert active[0]["id"] == task_ids[0]
            assert active[0]["type"] == "gen_shots"
            assert active[0]["target_id"] == fixture["episode_id"]
            assert active[0]["request_id"] is None
            assert active[0]["status"] == "queued"
            assert active[0]["progress"] == 0

            asyncio.run(_mark_generate_task_done(task_ids[0]))
            next_impact = client.post(f"{url}/impact", content=b"")
            assert next_impact.status_code == 200
            next_token = next_impact.json()["confirm_token"]
            assert isinstance(next_token, str) and next_token
            after_terminal = client.post(url, json={"confirm_token": next_token})
            assert after_terminal.status_code == 202
            task_ids.append(after_terminal.json()["task_id"])
            assert task_ids[-1] != task_ids[0]
    finally:
        asyncio.run(_write_script2shots_template(original_template))
        asyncio.run(_cleanup_generate_fixture(fixture, task_ids))
