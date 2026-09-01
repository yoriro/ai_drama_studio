from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import engine
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.schemas.assets import AssetPatch
from app.schemas.clips import ClipSlotEnabledPatch
from app.schemas.prompt_templates import PromptTemplatePatch
from app.schemas.projects import ProjectPatch
from app.schemas.shots import ShotPatch
from app.schemas.styles import StylePatch
from app.services.assets import delete_asset, set_current_asset_image, update_asset
from app.services.clips import (
    update_clip_slot_enabled,
    update_clip_slot_override,
)
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.services.projects import update_project
from app.services.prompt_templates import update_prompt_template
from app.services.shots import update_shot
from app.services.styles import update_style
from app.tasks.queue import EnqueueResult, TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
    _read_task,
)


Mutation = Callable[[AsyncSession], Awaitable[Any]]


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _name(prefix: str) -> str:
    return f"c009-t10-{prefix}-{uuid4().hex[:8]}"


async def _set_application_name(connection: Any, name: str) -> None:
    await connection.execute(
        text("SELECT set_config('application_name', :name, false)"),
        {"name": name},
    )
    await connection.commit()


async def _call_with_named_session(name: str, operation: Mutation) -> Any:
    async with engine.connect() as connection:
        await _set_application_name(connection, name)
        async with AsyncSession(
            bind=connection, expire_on_commit=False
        ) as session:
            return await operation(session)


async def _enqueue_with_gate(
    fixture: dict[str, object],
    name: str,
    entered: asyncio.Event,
    release: asyncio.Event,
) -> EnqueueResult:
    queue = TaskQueue()
    original_enqueue = queue.enqueue
    binding = load_minimax_binding_snapshot()

    async with engine.connect() as connection:
        await _set_application_name(connection, name)
        async with AsyncSession(
            bind=connection, expire_on_commit=False
        ) as session:

            async def gated_enqueue(
                enqueue_session: AsyncSession,
                task_type: str,
                target_id: int,
                payload: dict[str, object],
                request_id: str | None = None,
            ) -> EnqueueResult:
                entered.set()
                await release.wait()
                return await original_enqueue(
                    enqueue_session,
                    task_type,
                    target_id,
                    payload,
                    request_id=request_id,
                )

            queue.enqueue = gated_enqueue  # type: ignore[method-assign]
            return await enqueue_generate_clip_video(
                session,
                queue,
                int(fixture["clip_id"]),
                user_note=None,
                user_note_provided=False,
                request_id=None,
                workflow_binding=binding,
            )


async def _wait_for_lock_waiter(name: str) -> dict[str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        for _ in range(200):
            row = await connection.fetchrow(
                """
                SELECT state, wait_event_type
                FROM pg_stat_activity
                WHERE application_name = $1
                  AND state = 'active'
                  AND wait_event_type = 'Lock'
                """,
                name,
            )
            if row is not None:
                return {
                    "state": str(row["state"]),
                    "wait_event_type": str(row["wait_event_type"]),
                }
            await asyncio.sleep(0.01)
        raise AssertionError(f"row-lock waiter was not visible for {name}")
    finally:
        await connection.close()


async def _hold_asset_update(
    asset_id: int,
    name: str,
    ready: asyncio.Event,
    release: asyncio.Event,
) -> None:
    connection = await asyncpg.connect(
        _database_url(), server_settings={"application_name": _name("holder")}
    )
    transaction = connection.transaction()
    committed = False
    try:
        await transaction.start()
        row = await connection.fetchrow(
            "SELECT id FROM assets WHERE id = $1 FOR UPDATE", asset_id
        )
        assert row is not None
        await connection.execute(
            """
            UPDATE assets
            SET name = $1, description = $2, revision = revision + 1
            WHERE id = $3
            """,
            name,
            "资产屏障后的描述",
            asset_id,
        )
        ready.set()
        await release.wait()
        await transaction.commit()
        committed = True
    finally:
        if not committed and connection.is_in_transaction():
            await transaction.rollback()
        await connection.close()


async def _unbind_asset_from_shots(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            DELETE FROM shot_assets
            WHERE asset_id = $1 AND shot_id = ANY($2::int[])
            """,
            int(fixture["character_id"]),
            fixture["shot_ids"],
        )
    finally:
        await connection.close()


async def _add_noncurrent_asset_image(fixture: dict[str, object]) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, source, is_current)
            VALUES ($1, 'unused.png', $2, 'uploaded', false)
            RETURNING id
            """,
            int(fixture["character_id"]),
            "0" * 64,
        )
        assert image_id is not None
        return int(image_id)
    finally:
        await connection.close()


async def _read_asset(asset_id: int) -> dict[str, object] | None:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT id, name, description, revision FROM assets WHERE id = $1",
            asset_id,
        )
        return None if row is None else dict(row)
    finally:
        await connection.close()


async def _read_clip(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT user_note, revision, freshness, generation_state
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _read_slot(clip_id: int, slot_no: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT asset_id, enabled, override_image_path, override_sha256
            FROM clip_ref_slots
            WHERE clip_id = $1 AND slot_no = $2
            """,
            clip_id,
            slot_no,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _read_shot_description(shot_id: int) -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        description = await connection.fetchval(
            "SELECT description FROM shots WHERE id = $1", shot_id
        )
        assert isinstance(description, str)
        return description
    finally:
        await connection.close()


async def _run_gated_mutation(
    fixture: dict[str, object], mutation_name: str, mutation: Mutation
) -> tuple[dict[str, object], Any]:
    enqueue_name = _name("enqueue")
    mutation_name = f"{mutation_name}-{uuid4().hex[:8]}"
    entered = asyncio.Event()
    release = asyncio.Event()
    enqueue_task = asyncio.create_task(
        _enqueue_with_gate(fixture, enqueue_name, entered, release)
    )
    mutation_task: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        mutation_task = asyncio.create_task(
            _call_with_named_session(mutation_name, mutation)
        )
        waiter = await _wait_for_lock_waiter(mutation_name)
        assert waiter == {"state": "active", "wait_event_type": "Lock"}
        assert not mutation_task.done()
        release.set()
        result = await asyncio.wait_for(enqueue_task, timeout=10)
        mutation_result = await asyncio.wait_for(mutation_task, timeout=10)
        task = await _read_task(result.task.id)
        return task, mutation_result
    finally:
        release.set()
        if not enqueue_task.done():
            enqueue_task.cancel()
        if mutation_task is not None and not mutation_task.done():
            mutation_task.cancel()
        await asyncio.gather(enqueue_task, return_exceptions=True)
        if mutation_task is not None:
            await asyncio.gather(mutation_task, return_exceptions=True)


def test_c009_enabled_asset_lock_covers_bound_and_slot_only_assets(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", Path(tmp_path))

    async def run() -> None:
        for slot_only in (False, True):
            fixture = await _create_fixture(Path(tmp_path))
            holder_task: asyncio.Task[None] | None = None
            enqueue_task: asyncio.Task[EnqueueResult] | None = None
            holder_release = asyncio.Event()
            holder_ready = asyncio.Event()
            try:
                if slot_only:
                    await _unbind_asset_from_shots(fixture)
                expected_name = (
                    "槽位保留资产" if slot_only else "仍绑定资产"
                )
                holder_task = asyncio.create_task(
                    _hold_asset_update(
                        int(fixture["character_id"]),
                        expected_name,
                        holder_ready,
                        holder_release,
                    )
                )
                await holder_ready.wait()
                enqueue_name = _name("asset-waiter")
                enqueue_task = asyncio.create_task(
                    _call_with_named_session(
                        enqueue_name,
                        lambda session: enqueue_generate_clip_video(
                            session,
                            TaskQueue(),
                            int(fixture["clip_id"]),
                            user_note=None,
                            user_note_provided=False,
                            request_id=None,
                            workflow_binding=load_minimax_binding_snapshot(),
                        ),
                    )
                )
                waiter = await _wait_for_lock_waiter(enqueue_name)
                assert waiter == {"state": "active", "wait_event_type": "Lock"}
                assert not enqueue_task.done()
                holder_release.set()
                await asyncio.wait_for(holder_task, timeout=10)
                result = await asyncio.wait_for(enqueue_task, timeout=10)
                task = await _read_task(result.task.id)
                snapshot = task["payload"]["input_snapshot"]
                assert snapshot["references"][0]["asset_name"] == expected_name
                assert snapshot["references"][0]["asset_description"] == (
                    "资产屏障后的描述"
                )
                assert task["status"] == "queued"
                assert (await _read_asset(int(fixture["character_id"])))["name"] == (
                    expected_name
                )
            finally:
                holder_release.set()
                if enqueue_task is not None and not enqueue_task.done():
                    enqueue_task.cancel()
                if holder_task is not None and not holder_task.done():
                    holder_task.cancel()
                if enqueue_task is not None:
                    await asyncio.gather(enqueue_task, return_exceptions=True)
                if holder_task is not None:
                    await asyncio.gather(holder_task, return_exceptions=True)
                await _cleanup_fixture(fixture)
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("slot_only", [False, True], ids=["shot-bound", "slot-only"])
@pytest.mark.parametrize("operation", ["patch", "current", "delete"])
def test_c009_asset_mutations_wait_at_asset_then_clip_barrier(
    operation: str, slot_only: bool, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", Path(tmp_path))

    async def run() -> None:
        fixture = await _create_fixture(Path(tmp_path))
        second_image_id: int | None = None
        try:
            if slot_only:
                await _unbind_asset_from_shots(fixture)
            if operation == "patch":
                mutation = lambda session: update_asset(
                    session,
                    int(fixture["character_id"]),
                    AssetPatch(name="资产竞争后"),
                )
            elif operation == "current":
                second_image_id = await _add_noncurrent_asset_image(fixture)
                mutation = lambda session: set_current_asset_image(
                    session,
                    int(fixture["character_id"]),
                    second_image_id,
                )
            else:
                mutation = lambda session: delete_asset(
                    session, int(fixture["character_id"])
                )

            task, _mutation_result = await _run_gated_mutation(
                fixture, f"asset-{operation}", mutation
            )
            snapshot = task["payload"]["input_snapshot"]
            assert task["status"] == "queued"
            assert snapshot["references"][0]["asset_name"] == "林夏"
            assert snapshot["references"][0]["asset_description"] == "黑发白衬衫"
            clip = await _read_clip(int(fixture["clip_id"]))
            assert clip["freshness"] == "stale"
            if operation == "patch":
                asset = await _read_asset(int(fixture["character_id"]))
                assert asset is not None
                assert asset["name"] == "资产竞争后"
            elif operation == "current":
                connection = await asyncpg.connect(_database_url())
                try:
                    current_id = await connection.fetchval(
                        """
                        SELECT id FROM asset_images
                        WHERE asset_id = $1 AND is_current = true
                        """,
                        int(fixture["character_id"]),
                    )
                    assert current_id == second_image_id
                finally:
                    await connection.close()
            else:
                assert await _read_asset(int(fixture["character_id"])) is None
                slot = await _read_slot(int(fixture["clip_id"]), 1)
                assert slot["asset_id"] is None
        finally:
            await _cleanup_fixture(fixture)
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("mutation_kind", ["shot", "slot_enabled", "slot_override"])
def test_c009_clip_mutations_wait_at_enqueue_clip_barrier(
    mutation_kind: str, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", Path(tmp_path))

    async def run() -> None:
        fixture = await _create_fixture(Path(tmp_path))
        try:
            original_slot = await _read_slot(int(fixture["clip_id"]), 3)
            if mutation_kind == "shot":
                mutation = lambda session: update_shot(
                    session,
                    int(fixture["shot_ids"][0]),
                    ShotPatch(description="分镜竞争后"),
                )
            elif mutation_kind == "slot_enabled":
                mutation = lambda session: update_clip_slot_enabled(
                    session,
                    int(fixture["clip_id"]),
                    2,
                    ClipSlotEnabledPatch(enabled=True),
                )
            else:
                mutation = lambda session: update_clip_slot_override(
                    session,
                    int(fixture["clip_id"]),
                    3,
                    upload=None,
                    clear_override=True,
                )
            task, _mutation_result = await _run_gated_mutation(
                fixture, mutation_kind, mutation
            )
            snapshot = task["payload"]["input_snapshot"]
            assert task["status"] == "queued"
            if mutation_kind == "shot":
                assert snapshot["shots"][0]["description"] == "街角等待"
                assert (
                    await _read_shot_description(int(fixture["shot_ids"][0]))
                    == "分镜竞争后"
                )
            elif mutation_kind == "slot_enabled":
                assert [
                    item["slot_no"] for item in snapshot["references"]
                ] == [1, 3]
                slot = await _read_slot(int(fixture["clip_id"]), 2)
                assert slot["enabled"] is True
            else:
                slot = await _read_slot(int(fixture["clip_id"]), 3)
                assert slot["override_image_path"] is None
                assert slot["override_sha256"] is None
                reference = next(
                    item
                    for item in snapshot["references"]
                    if item["slot_no"] == 3
                )
                assert reference["image_source"] == "override"
                assert reference["override_sha256"] == original_slot[
                    "override_sha256"
                ]
            clip = await _read_clip(int(fixture["clip_id"]))
            assert clip["freshness"] == "stale"
        finally:
            await _cleanup_fixture(fixture)
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("mutation_kind", ["project", "style", "template"])
def test_c009_project_style_template_mutations_wait_after_clip_lock(
    mutation_kind: str, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", Path(tmp_path))

    async def run() -> None:
        fixture = await _create_fixture(Path(tmp_path))
        try:
            template = (
                "shots={{shots}}|references={{references}}|style={{style}}|"
                "duration={{requested_duration}}|note={{user_note}}"
            )
            if mutation_kind == "project":
                mutation = lambda session: update_project(
                    session,
                    int(fixture["project_id"]),
                    ProjectPatch(name="项目竞争后"),
                )
            elif mutation_kind == "style":
                mutation = lambda session: update_style(
                    session,
                    int(fixture["style_id"]),
                    StylePatch(prompt_fragment="风格竞争后"),
                )
            else:
                mutation = lambda session: update_prompt_template(
                    session,
                    "minimaxh3",
                    PromptTemplatePatch(content=template + "|模板竞争后"),
                )
            task, _mutation_result = await _run_gated_mutation(
                fixture, mutation_kind, mutation
            )
            snapshot = task["payload"]["input_snapshot"]
            assert task["status"] == "queued"
            assert snapshot["style"] == "电影写实"
            assert snapshot["template_content"] == template
            if mutation_kind == "project":
                connection = await asyncpg.connect(_database_url())
                try:
                    name = await connection.fetchval(
                        "SELECT name FROM projects WHERE id = $1",
                        int(fixture["project_id"]),
                    )
                    assert name == "项目竞争后"
                finally:
                    await connection.close()
            elif mutation_kind == "style":
                connection = await asyncpg.connect(_database_url())
                try:
                    fragment = await connection.fetchval(
                        "SELECT prompt_fragment FROM styles WHERE id = $1",
                        int(fixture["style_id"]),
                    )
                    assert fragment == "风格竞争后"
                finally:
                    await connection.close()
            else:
                connection = await asyncpg.connect(_database_url())
                try:
                    content = await connection.fetchval(
                        "SELECT content FROM prompt_templates WHERE key = 'minimaxh3'"
                    )
                    assert content == template + "|模板竞争后"
                finally:
                    await connection.close()
            clip = await _read_clip(int(fixture["clip_id"]))
            assert clip["freshness"] == "fresh"
        finally:
            await _cleanup_fixture(fixture)
        await engine.dispose()

    asyncio.run(run())
