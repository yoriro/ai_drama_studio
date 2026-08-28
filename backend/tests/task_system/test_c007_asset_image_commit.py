import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from PIL import Image
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.db.session import async_session_factory, engine
from app.services import asset_image_commit as commit_service
from app.services.asset_image_commit import (
    GeneratedPng,
    cleanup_generated_png,
    commit_generated_asset_image,
    write_generated_png,
)
from app.tasks.queue import (
    ClaimedTask,
    TaskChange,
    TaskConflictError,
    TaskQueue,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (4, 4), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (23, 81, 144))
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


async def _chunks(content: bytes, chunk_size: int = 7):
    for offset in range(0, len(content), chunk_size):
        yield content[offset : offset + chunk_size]


async def _create_fixture(*, with_dependents: bool = False) -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '水墨写实')
            RETURNING id
            """,
            "C007 T7 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 T7 project " + uuid4().hex,
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '林夏', '黑发白衬衫', 'manual', 1)
            RETURNING id
            """,
            project_id,
        )
        fixture = {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
        }
        if with_dependents:
            episode_id = await connection.fetchval(
                """
                INSERT INTO episodes (project_id, seq, title, script_text)
                VALUES ($1, 1, 'T7 episode', 'T7 script')
                RETURNING id
                """,
                project_id,
            )
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, 1, 2.0, '远景', '固定', '林夏站在窗边', '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
            )
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                shot_id,
                asset_id,
            )
            clip_id = await connection.fetchval(
                """
                INSERT INTO clips
                    (episode_id, requested_duration, generation_state, freshness, revision)
                VALUES ($1, 2, 'empty', 'fresh', 1)
                RETURNING id
                """,
                episode_id,
            )
            await connection.execute(
                "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
                clip_id,
                shot_id,
            )
            fixture["episode_id"] = int(episode_id)
            fixture["shot_id"] = int(shot_id)
            fixture["clip_id"] = int(clip_id)
        return fixture
    finally:
        await connection.close()


async def _insert_task(
    fixture: dict[str, int],
    *,
    status: str = "running",
    source_revision: int = 1,
    input_hash: str = "input-hash",
    cached_prompt: str | None = None,
    seed: int = 123,
) -> tuple[int, dict[str, object]]:
    payload: dict[str, object] = {
        "input_snapshot": {
            "asset": {
                "id": fixture["asset_id"],
                "project_id": fixture["project_id"],
                "type": "character",
                "name": "林夏",
                "description": "黑发白衬衫",
                "revision": source_revision,
            },
            "style": "水墨写实",
            "template_key": "zimage",
            "template_content": "asset={{asset}}|style={{style}}|note={{user_note}}",
            "user_note": None,
            "rendered_prompt": "rendered prompt",
            "model": "test-model",
            "temperature": 0.2,
            "guided_json_schema": {"type": "object"},
            "workflow": {
                "name": "zimage.json",
                "hash": "workflow-hash",
                "prompt_path": "6.inputs.text",
                "seed_path": "3.inputs.seed",
                "output_node": "9",
                "definition": {},
            },
            "seed": seed,
            "comfy_prompt_id": str(uuid4()),
            "cached_prompt": cached_prompt,
        },
        "input_hash": input_hash,
        "source_revisions": {
            "asset": {
                "id": fixture["asset_id"],
                "revision": source_revision,
            }
        },
    }
    connection = await asyncpg.connect(_database_url())
    try:
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks (type, target_id, payload, status, progress)
            VALUES ('gen_asset_image', $1, $2::jsonb, $3, 0.0)
            RETURNING id
            """,
            fixture["asset_id"],
            json.dumps(payload, ensure_ascii=False),
            status,
        )
        return int(task_id), payload
    finally:
        await connection.close()


def _claimed(
    task_id: int, fixture: dict[str, int], payload: dict[str, object]
) -> ClaimedTask:
    return ClaimedTask(
        id=task_id,
        type="gen_asset_image",
        target_id=fixture["asset_id"],
        request_id=None,
        payload=copy.deepcopy(payload),
    )


async def _insert_current_image(fixture: dict[str, int]) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current)
            VALUES ($1, 'existing.png', 'existing-sha256', 1, 'uploaded', true)
            RETURNING id
            """,
            fixture["asset_id"],
        )
        return int(image_id)
    finally:
        await connection.close()


async def _update_asset_revision(fixture: dict[str, int], revision: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE assets SET revision = $1 WHERE id = $2",
            revision,
            fixture["asset_id"],
        )
    finally:
        await connection.close()


async def _request_cancel(task_id: int) -> TaskChange:
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.request_cancel(session, task_id)


async def _read_task(task_id: int) -> asyncpg.Record:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT status, progress, error_msg FROM tasks WHERE id = $1",
            task_id,
        )
        assert row is not None
        return row
    finally:
        await connection.close()


async def _read_asset_state(
    fixture: dict[str, int],
) -> tuple[asyncpg.Record, list[asyncpg.Record]]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            """
            SELECT revision, image_prompt_cache, image_prompt_hash
            FROM assets WHERE id = $1
            """,
            fixture["asset_id"],
        )
        image_rows = await connection.fetch(
            """
            SELECT id, asset_id, file_path, sha256, seed, source, is_current,
                   built_prompt, input_hash, input_snapshot, user_note
            FROM asset_images WHERE asset_id = $1 ORDER BY id
            """,
            fixture["asset_id"],
        )
        assert asset is not None
        images = []
        for row in image_rows:
            image = dict(row)
            if isinstance(image["input_snapshot"], str):
                image["input_snapshot"] = json.loads(image["input_snapshot"])
            images.append(image)
        return asset, images
    finally:
        await connection.close()


async def _read_dependent_state(
    fixture: dict[str, int],
) -> tuple[asyncpg.Record, asyncpg.Record]:
    connection = await asyncpg.connect(_database_url())
    try:
        shot = await connection.fetchrow(
            "SELECT status, revision FROM shots WHERE id = $1",
            fixture["shot_id"],
        )
        clip = await connection.fetchrow(
            "SELECT freshness FROM clips WHERE id = $1",
            fixture["clip_id"],
        )
        assert shot is not None and clip is not None
        return shot, clip
    finally:
        await connection.close()


async def _delete_asset(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
        )
    finally:
        await connection.close()


async def _cleanup_fixture(
    fixture: dict[str, int], task_ids: list[int]
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = $1", fixture["asset_id"]
        )
        if "clip_id" in fixture:
            await connection.execute(
                "DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"]
            )
        if "shot_id" in fixture:
            await connection.execute(
                "DELETE FROM shot_assets WHERE shot_id = $1", fixture["shot_id"]
            )
        if "clip_id" in fixture:
            await connection.execute(
                "DELETE FROM clips WHERE id = $1", fixture["clip_id"]
            )
        if "shot_id" in fixture:
            await connection.execute(
                "DELETE FROM shots WHERE id = $1", fixture["shot_id"]
            )
        if "episode_id" in fixture:
            await connection.execute(
                "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
            )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


class _CommitFailureSession(AsyncSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sync_session.info["c007_t7_fail_commit"] = True


class _CompleteGateQueue(TaskQueue):
    def __init__(self) -> None:
        super().__init__(async_session_factory)
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()

    async def complete(self, session, task_id: int) -> TaskChange:
        self.complete_entered.set()
        await self.allow_complete.wait()
        return await super().complete(session, task_id)


def test_generated_png_stream_validates_raw_png_and_cleans_temp(tmp_path: Path) -> None:
    async def run() -> None:
        png = _png_bytes((23, 81, 144))
        generated = await write_generated_png(_chunks(png), data_dir=tmp_path)
        assert generated.temp_path.is_file()
        assert generated.temp_path.parent == tmp_path / "tmp" / "asset-images"
        assert generated.temp_path.read_bytes() == png
        assert generated.sha256 == hashlib.sha256(png).hexdigest()
        cleanup_generated_png(generated, data_dir=tmp_path)
        assert not generated.temp_path.exists()

        with pytest.raises(ValueError, match="empty"):
            await write_generated_png(_chunks(b""), data_dir=tmp_path)
        with pytest.raises(ValueError, match="not a PNG"):
            await write_generated_png(_chunks(_jpeg_bytes()), data_dir=tmp_path)
        assert not list((tmp_path / "tmp" / "asset-images").glob("*.upload"))

    asyncio.run(run())


def test_commit_generated_image_sets_safe_current_cache_and_cascade(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        fixture = await _create_fixture(with_dependents=True)
        task_id, payload = await _insert_task(fixture)
        try:
            png = _png_bytes((1, 2, 3))
            generated = await write_generated_png(_chunks(png), data_dir=tmp_path)
            change = await _commit_direct(
                fixture,
                task_id,
                payload,
                generated,
                tmp_path,
                built_prompt="built prompt",
            )
            assert change is not None and change.changed is True
            asset, images = await _read_asset_state(fixture)
            assert asset["revision"] == 2
            assert asset["image_prompt_cache"] == "built prompt"
            assert asset["image_prompt_hash"] == "input-hash"
            assert len(images) == 1
            image = images[0]
            assert image["asset_id"] == fixture["asset_id"]
            assert image["sha256"] == hashlib.sha256(png).hexdigest()
            assert image["seed"] == 123
            assert image["source"] == "generated"
            assert image["is_current"] is True
            assert image["built_prompt"] == "built prompt"
            assert image["input_hash"] == "input-hash"
            assert image["input_snapshot"] == payload["input_snapshot"]
            assert image["user_note"] is None
            formal_path = tmp_path / Path(image["file_path"])
            assert formal_path.is_file()
            assert formal_path.read_bytes() == png
            assert not generated.temp_path.exists()
            shot, clip = await _read_dependent_state(fixture)
            assert shot["status"] == "changed"
            assert shot["revision"] == 2
            assert clip["freshness"] == "stale"
            task = await _read_task(task_id)
            assert task["status"] == "done"
            assert task["progress"] == 1
            assert task["error_msg"] is None
        finally:
            await _cleanup_fixture(fixture, [task_id])
            await engine.dispose()

    asyncio.run(run())


def test_commit_generated_image_preserves_noncurrent_for_revision_or_current(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        mismatch = await _create_fixture()
        mismatch_task, mismatch_payload = await _insert_task(mismatch)
        existing = await _create_fixture()
        existing_task, existing_payload = await _insert_task(
            existing,
            input_hash="cached-hash",
            cached_prompt="cached prompt",
        )
        await _insert_current_image(existing)
        connection = await asyncpg.connect(_database_url())
        try:
            await connection.execute(
                "UPDATE assets SET image_prompt_cache = 'cached prompt', image_prompt_hash = 'cached-hash' WHERE id = $1",
                existing["asset_id"],
            )
        finally:
            await connection.close()
        try:
            await _update_asset_revision(mismatch, 2)
            mismatch_generated = await write_generated_png(
                _chunks(_png_bytes((4, 5, 6))), data_dir=tmp_path
            )
            mismatch_change = await _commit_direct(
                mismatch,
                mismatch_task,
                mismatch_payload,
                mismatch_generated,
                tmp_path,
                built_prompt="new prompt",
            )
            assert mismatch_change is not None
            mismatch_asset, mismatch_images = await _read_asset_state(mismatch)
            assert mismatch_asset["revision"] == 2
            assert len(mismatch_images) == 1
            assert mismatch_images[0]["is_current"] is False

            existing_generated = await write_generated_png(
                _chunks(_png_bytes((7, 8, 9))), data_dir=tmp_path
            )
            existing_change = await _commit_direct(
                existing,
                existing_task,
                existing_payload,
                existing_generated,
                tmp_path,
                built_prompt="cached prompt",
            )
            assert existing_change is not None
            existing_asset, existing_images = await _read_asset_state(existing)
            assert existing_asset["revision"] == 1
            assert existing_asset["image_prompt_cache"] == "cached prompt"
            assert existing_asset["image_prompt_hash"] == "cached-hash"
            assert len(existing_images) == 2
            assert existing_images[0]["is_current"] is True
            assert existing_images[1]["is_current"] is False
        finally:
            await _cleanup_fixture(mismatch, [mismatch_task])
            await _cleanup_fixture(existing, [existing_task])
            await engine.dispose()

    asyncio.run(run())


def test_deleted_asset_fails_task_and_leaves_no_image_or_file(tmp_path: Path) -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        task_id, _payload = await _insert_task(fixture, status="queued")
        generated = await write_generated_png(
            _chunks(_png_bytes((10, 11, 12))), data_dir=tmp_path
        )
        await _delete_asset(fixture)

        async def handler(task: ClaimedTask, context) -> None:
            async with async_session_factory() as session:
                await commit_generated_asset_image(
                    session,
                    context.queue,
                    task,
                    generated,
                    built_prompt="built prompt",
                    data_dir=tmp_path,
                )

        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task = await _read_task(task_id)
            assert task["status"] == "failed"
            assert "target asset no longer exists" in task["error_msg"]
            assert not generated.temp_path.exists()
            assert not list((tmp_path / "projects").rglob("*.png"))
            connection = await asyncpg.connect(_database_url())
            try:
                assert await connection.fetchval(
                    "SELECT count(*) FROM asset_images WHERE asset_id = $1",
                    fixture["asset_id"],
                ) == 0
            finally:
                await connection.close()
        finally:
            await _cleanup_fixture(fixture, [task_id])
            await engine.dispose()

    asyncio.run(run())


def test_database_commit_failure_moves_formal_png_to_trash(tmp_path: Path) -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        task_id, _payload = await _insert_task(fixture, status="queued")
        png = _png_bytes((13, 14, 15))
        generated = await write_generated_png(_chunks(png), data_dir=tmp_path)
        failing_factory = async_sessionmaker(
            engine,
            class_=_CommitFailureSession,
            expire_on_commit=False,
        )

        def fail_before_commit(sync_session: Session) -> None:
            if sync_session.info.get("c007_t7_fail_commit"):
                raise RuntimeError("simulated database commit failure")

        event.listen(Session, "before_commit", fail_before_commit)
        try:
            async def handler(task: ClaimedTask, context) -> None:
                async with failing_factory() as session:
                    await commit_generated_asset_image(
                        session,
                        context.queue,
                        task,
                        generated,
                        built_prompt="built prompt",
                        data_dir=tmp_path,
                    )

            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task = await _read_task(task_id)
            assert task["status"] == "failed"
            assert "simulated database commit failure" in task["error_msg"]
            assert not generated.temp_path.exists()
            formal_root = (
                tmp_path
                / "projects"
                / str(fixture["project_id"])
                / "assets"
                / str(fixture["asset_id"])
            )
            assert not list(formal_root.glob("*.png"))
            trash_root = tmp_path / "trash" / formal_root.relative_to(tmp_path)
            trash_files = list(trash_root.glob("*.png"))
            assert len(trash_files) == 1
            assert trash_files[0].read_bytes() == png
            asset, images = await _read_asset_state(fixture)
            assert asset["image_prompt_cache"] is None
            assert asset["image_prompt_hash"] is None
            assert images == []
        finally:
            event.remove(Session, "before_commit", fail_before_commit)
            await _cleanup_fixture(fixture, [task_id])
            await engine.dispose()

    asyncio.run(run())


def test_trash_compensation_failure_preserves_primary_error(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        task_id, _payload = await _insert_task(fixture, status="queued")
        generated = await write_generated_png(
            _chunks(_png_bytes((16, 17, 18))), data_dir=tmp_path
        )
        failing_factory = async_sessionmaker(
            engine,
            class_=_CommitFailureSession,
            expire_on_commit=False,
        )

        def fail_before_commit(sync_session: Session) -> None:
            if sync_session.info.get("c007_t7_fail_commit"):
                raise RuntimeError("simulated database commit failure")

        def fail_trash(*_args, **_kwargs) -> None:
            raise OSError("simulated trash failure")

        monkeypatch.setattr(commit_service, "move_asset_image_to_trash", fail_trash)
        event.listen(Session, "before_commit", fail_before_commit)
        try:
            async def handler(task: ClaimedTask, context) -> None:
                async with failing_factory() as session:
                    await commit_generated_asset_image(
                        session,
                        context.queue,
                        task,
                        generated,
                        built_prompt="built prompt",
                        data_dir=tmp_path,
                    )

            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task = await _read_task(task_id)
            assert task["status"] == "failed"
            assert "simulated database commit failure" in task["error_msg"]
            assert "simulated trash failure" in task["error_msg"]
            assert not generated.temp_path.exists()
            formal_root = (
                tmp_path
                / "projects"
                / str(fixture["project_id"])
                / "assets"
                / str(fixture["asset_id"])
            )
            assert len(list(formal_root.glob("*.png"))) == 1
            assert not list((tmp_path / "trash").rglob("*.png"))
            asset, images = await _read_asset_state(fixture)
            assert asset["image_prompt_cache"] is None
            assert images == []
        finally:
            event.remove(Session, "before_commit", fail_before_commit)
            await _cleanup_fixture(fixture, [task_id])
            await engine.dispose()

    asyncio.run(run())


def test_cancel_and_done_final_transaction_has_one_winner(tmp_path: Path) -> None:
    async def run() -> None:
        done_fixture = await _create_fixture()
        done_task_id, done_payload = await _insert_task(done_fixture)
        done_generated = await write_generated_png(
            _chunks(_png_bytes((19, 20, 21))), data_dir=tmp_path
        )
        done_queue = _CompleteGateQueue()
        cancel_started = asyncio.Event()

        async def commit_done() -> TaskChange | None:
            async with async_session_factory() as session:
                return await commit_generated_asset_image(
                    session,
                    done_queue,
                    _claimed(done_task_id, done_fixture, done_payload),
                    done_generated,
                    built_prompt="done prompt",
                    data_dir=tmp_path,
                )

        async def request_cancel() -> TaskChange:
            cancel_started.set()
            return await _request_cancel(done_task_id)

        commit_task = asyncio.create_task(commit_done())
        await asyncio.wait_for(done_queue.complete_entered.wait(), timeout=5)
        cancel_task = asyncio.create_task(request_cancel())
        await asyncio.wait_for(cancel_started.wait(), timeout=5)
        assert not cancel_task.done()
        done_queue.allow_complete.set()
        done_change = await asyncio.wait_for(commit_task, timeout=5)
        assert done_change is not None and done_change.changed is True
        with pytest.raises(TaskConflictError):
            await asyncio.wait_for(cancel_task, timeout=5)
        done_state = await _read_task(done_task_id)
        assert done_state["status"] == "done"
        _, done_images = await _read_asset_state(done_fixture)
        assert len(done_images) == 1

        cancel_fixture = await _create_fixture()
        cancel_task_id, cancel_payload = await _insert_task(cancel_fixture)
        cancel_generated = await write_generated_png(
            _chunks(_png_bytes((22, 23, 24))), data_dir=tmp_path
        )
        try:
            connection = await asyncpg.connect(_database_url())
            try:
                await connection.execute(
                    "UPDATE tasks SET cancel_requested_at = now() WHERE id = $1",
                    cancel_task_id,
                )
            finally:
                await connection.close()
            async with async_session_factory() as session:
                canceled_change = await commit_generated_asset_image(
                    session,
                    TaskQueue(async_session_factory),
                    _claimed(cancel_task_id, cancel_fixture, cancel_payload),
                    cancel_generated,
                    built_prompt="canceled prompt",
                    data_dir=tmp_path,
                )
            assert canceled_change is None
            async with async_session_factory() as session:
                async with session.begin():
                    safe_point = await TaskQueue(async_session_factory).cancel_safe_point(
                        session, cancel_task_id
                    )
            assert safe_point.task is not None
            assert safe_point.task.status == "canceled"
            assert not cancel_generated.temp_path.exists()
            cancel_asset, cancel_images = await _read_asset_state(cancel_fixture)
            assert cancel_asset["image_prompt_cache"] is None
            assert cancel_images == []
        finally:
            await _cleanup_fixture(done_fixture, [done_task_id])
            await _cleanup_fixture(cancel_fixture, [cancel_task_id])
            await engine.dispose()

    asyncio.run(run())


async def _commit_direct(
    fixture: dict[str, int],
    task_id: int,
    payload: dict[str, object],
    generated: GeneratedPng,
    data_dir: Path,
    *,
    built_prompt: str,
) -> TaskChange | None:
    async with async_session_factory() as session:
        return await commit_generated_asset_image(
            session,
            TaskQueue(async_session_factory),
            _claimed(task_id, fixture, payload),
            generated,
            built_prompt=built_prompt,
            data_dir=data_dir,
        )
