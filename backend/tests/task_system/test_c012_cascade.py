from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.main import app
from app.services.clip_video_commit import commit_generated_clip_video
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.services.prompt_templates import update_prompt_template
from app.services.styles import update_style
from app.services.video_files import clip_video_paths
from app.schemas.prompt_templates import PromptTemplatePatch
from app.schemas.styles import StylePatch
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.gen_shots import gen_shots_handler
from app.tasks.queue import ClaimedTask, TaskQueue
from app.tasks.gen_clip_video import GeneratedClipVideo
from tests.api.test_c008_asset_slot_cascade import (
    _cleanup_fixture as cleanup_asset_fixture,
    _create_fixture as create_asset_fixture,
    _read_state as read_asset_state,
)
from tests.api.test_c009_generate_video import (
    _cleanup_fixture as cleanup_video_fixture,
    _create_fixture as create_video_fixture,
)
from tests.task_system.test_c006_gen_shots import (
    _cleanup_replace_fixture,
    _create_replace_fixture,
    _insert_task as insert_shot_task,
    _read_replace_structure,
    _replace_payload,
    _response as shot_response,
    _run_task as run_shot_task,
    _shot,
)
from tests.task_system.test_c009_clip_video_commit import (
    _read_commit_state,
    _write_temp,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _insert_task(
    *,
    task_type: str,
    target_id: int,
    payload: dict[str, object],
    session_factory: async_sessionmaker,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            from app.models import Task

            task = Task(
                type=task_type,
                target_id=target_id,
                request_id=None,
                payload=payload,
                status="queued",
                progress=0.0,
            )
            session.add(task)
            await session.flush()
            return int(task.id)


async def _read_task(task_id: int) -> tuple[str, str | None]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT status, error_msg FROM tasks WHERE id = $1", task_id
        )
        assert row is not None
        return str(row["status"]), row["error_msg"]
    finally:
        await connection.close()


async def _read_episode_markers(episode_id: int) -> tuple[object, ...]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT script_revision, assets_generated_script_revision, "
            "shots_generated_script_revision FROM episodes WHERE id = $1",
            episode_id,
        )
        assert row is not None
        return tuple(row)
    finally:
        await connection.close()


async def _set_episode_markers(
    episode_id: int, *, assets_marker: int | None, shots_marker: int | None
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE episodes SET assets_generated_script_revision = $1, "
            "shots_generated_script_revision = $2 WHERE id = $3",
            assets_marker,
            shots_marker,
            episode_id,
        )
    finally:
        await connection.close()


async def _read_project_assets(project_id: int) -> list[tuple[object, ...]]:
    connection = await asyncpg.connect(_database_url())
    try:
        return [
            tuple(row)
            for row in await connection.fetch(
                "SELECT id, type, name, description, source, revision "
                "FROM assets WHERE project_id = $1 ORDER BY id",
                project_id,
            )
        ]
    finally:
        await connection.close()


async def _read_asset_edit_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            "SELECT name, description, revision FROM assets WHERE id = $1",
            fixture["character_id"],
        )
        shots = await connection.fetch(
            "SELECT id, status, revision FROM shots WHERE id = ANY($1::int[]) ORDER BY id",
            fixture["shot_ids"],
        )
        clips = await connection.fetch(
            "SELECT id, freshness, revision FROM clips WHERE id = $1",
            fixture["clip_id"],
        )
        images = await connection.fetch(
            "SELECT id, file_path, sha256, is_current FROM asset_images "
            "WHERE asset_id = $1 ORDER BY id",
            fixture["character_id"],
        )
        assert asset is not None
        return {
            "asset": tuple(asset),
            "shots": [tuple(row) for row in shots],
            "clips": [tuple(row) for row in clips],
            "images": [tuple(row) for row in images],
        }
    finally:
        await connection.close()


async def _add_second_image(fixture: dict[str, object], data_dir: Path) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        image_id = int(
            await connection.fetchval(
                "INSERT INTO asset_images (asset_id, file_path, sha256, source, is_current) "
                "VALUES ($1, 'pending', $2, 'uploaded', false) RETURNING id",
                fixture["character_id"],
                "0" * 64,
            )
        )
        relative_path = Path(
            "projects",
            str(fixture["project_id"]),
            "assets",
            str(fixture["character_id"]),
            f"{image_id}.png",
        )
        image_path = data_dir / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        content = b"c012 second current image"
        image_path.write_bytes(content)
        await connection.execute(
            "UPDATE asset_images SET file_path = $1, sha256 = $2 WHERE id = $3",
            relative_path.as_posix(),
            hashlib.sha256(content).hexdigest(),
            image_id,
        )
        return image_id
    finally:
        await connection.close()


async def _synchronize_slot_override_digests(
    fixture: dict[str, object], data_dir: Path
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        for media in fixture["target_media"]:
            if media["kind"] != "slot_override":
                continue
            content = (data_dir / Path(media["path"])).read_bytes()
            await connection.execute(
                "UPDATE clip_ref_slots SET override_sha256 = $1 WHERE id = $2",
                hashlib.sha256(content).hexdigest(),
                media["id"],
            )
    finally:
        await connection.close()


class _AssetsVLLM:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.wake_calls = 0
        self.chat_calls = 0

    async def wake(self) -> None:
        self.wake_calls += 1

    async def structured_chat(self, **_request: object) -> dict[str, object]:
        self.chat_calls += 1
        return self.response


class _FailingAssetsVLLM:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.wake_calls = 0
        self.chat_calls = 0

    async def wake(self) -> None:
        self.wake_calls += 1

    async def structured_chat(self, **_request: object) -> dict[str, object]:
        self.chat_calls += 1
        raise self.error


class _ShotsVLLM:
    def __init__(self, response: dict[str, object] | None = None, error: BaseException | None = None) -> None:
        self.response = response
        self.error = error
        self.wake_calls = 0
        self.chat_calls = 0

    async def wake(self) -> None:
        self.wake_calls += 1

    async def structured_chat(self, **_request: object) -> dict[str, object]:
        self.chat_calls += 1
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _HealthProbe:
    async def health(self) -> None:
        return None


async def _idle_worker(
    self: TaskQueue,
    *,
    handlers: object,
    stop_event: asyncio.Event | None = None,
    poll_interval: float = 0.25,
    stop_when_idle: bool = False,
) -> None:
    del self, handlers, poll_interval, stop_when_idle
    assert stop_event is not None
    await stop_event.wait()


def _isolated_engine() -> tuple[AsyncEngine, async_sessionmaker]:
    isolated_engine = create_async_engine(os.environ["DATABASE_URL"])
    return isolated_engine, async_sessionmaker(
        isolated_engine, expire_on_commit=False
    )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    isolated_engine: AsyncEngine,
    session_factory: async_sessionmaker,
    *,
    idle_worker: bool = False,
) -> None:
    import app.db.session as db_session
    import app.main as main_module
    import app.services.gen_shots as gen_shots_service
    import app.tasks.gen_assets as gen_assets_module
    import app.tasks.gen_shots as gen_shots_module
    import app.tasks.queue as queue_module

    monkeypatch.setattr(db_session, "engine", isolated_engine)
    monkeypatch.setattr(db_session, "async_session_factory", session_factory)
    monkeypatch.setattr(main_module, "engine", isolated_engine)
    monkeypatch.setattr(main_module, "async_session_factory", session_factory)

    async def dispose_isolated_engine() -> None:
        await isolated_engine.dispose()

    monkeypatch.setattr(main_module, "dispose_engine", dispose_isolated_engine)
    monkeypatch.setattr(queue_module, "engine", isolated_engine)
    monkeypatch.setattr(gen_assets_module, "async_session_factory", session_factory)
    monkeypatch.setattr(gen_shots_module, "async_session_factory", session_factory)
    monkeypatch.setattr(gen_shots_service, "async_session_factory", session_factory)
    if idle_worker:
        monkeypatch.setattr(TaskQueue, "run_worker", _idle_worker)
        monkeypatch.setattr(
            app.state, "vllm_client_factory", lambda _url: _HealthProbe()
        )
        monkeypatch.setattr(
            app.state, "comfy_client_factory", lambda _url: _HealthProbe()
        )


async def _enqueue_and_claim_with_factory(
    fixture: dict[str, object], session_factory: async_sessionmaker
) -> tuple[TaskQueue, ClaimedTask]:
    from app.integrations.workflow_binding import load_minimax_binding_snapshot

    queue = TaskQueue(session_factory)
    async with session_factory() as session:
        await enqueue_generate_clip_video(
            session,
            queue,
            fixture["clip_id"],
            user_note=None,
            user_note_provided=False,
            request_id=None,
            workflow_binding=load_minimax_binding_snapshot(),
        )
    async with session_factory() as session:
        async with session.begin():
            change = await queue.claim_next(session)
        assert change is not None and change.changed and change.task is not None
        task = change.task
        return queue, ClaimedTask(
            id=int(task.id),
            type="gen_clip_video",
            target_id=int(task.target_id),
            request_id=task.request_id,
            payload=json.loads(json.dumps(task.payload)),
        )


async def _run_assets_task(
    task_id: int,
    fake: _AssetsVLLM,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker,
) -> None:
    monkeypatch.setattr("app.tasks.gen_assets.VLLMClient", lambda _url: fake)
    await TaskQueue(session_factory).run_worker(
        handlers={"gen_assets": gen_assets_handler},
        poll_interval=0.01,
        stop_when_idle=True,
    )
    status, error = await _read_task(task_id)
    assert status == "done", error


@pytest.mark.parametrize(
    "row",
    [
        "edit_script",
        "regenerate_assets",
        "regenerate_shots",
        "edit_asset",
        "delete_asset",
        "edit_shot_binding",
        "edit_style_template",
        "delete_clip",
        "clip_success",
    ],
)
def test_c012_cascade_matrix(
    row: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    if row == "edit_script":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory, idle_worker=True)
            fixture = await _create_replace_fixture(tmp_path)
            try:
                await _set_episode_markers(
                    fixture["target_episode_id"], assets_marker=4, shots_marker=4
                )
                before = await _read_replace_structure(fixture)
                before_markers = await _read_episode_markers(fixture["target_episode_id"])
                with TestClient(app) as client:
                    response = client.patch(
                        f"/api/episodes/{fixture['target_episode_id']}",
                        json={"script_text": "目标剧本已编辑"},
                    )
                assert response.status_code == 200
                after = await _read_replace_structure(fixture)
                assert after == before
                assert await _read_episode_markers(fixture["target_episode_id"]) == (5, 4, 4)
                assert before_markers == (4, 4, 4)
            finally:
                await _cleanup_replace_fixture(fixture, [])
        asyncio.run(run())
        return

    if row == "regenerate_assets":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory)
            fixture = await _create_replace_fixture(tmp_path)
            task_ids: list[int] = []
            try:
                before_structure = await _read_replace_structure(fixture)
                before_assets = await _read_project_assets(fixture["project_id"])
                payload = {
                    "input_snapshot": {
                        "episode_id": fixture["target_episode_id"],
                        "project_id": fixture["project_id"],
                        "script": "目标剧本",
                        "script_revision": 4,
                        "rendered_prompt": "R2 regenerated assets",
                        "model": "controlled-model",
                        "temperature": 0.2,
                    },
                    "input_hash": None,
                    "source_revisions": {},
                }
                task_id = await _insert_task(
                    task_type="gen_assets",
                    target_id=fixture["target_episode_id"],
                    payload=payload,
                    session_factory=session_factory,
                )
                task_ids.append(task_id)
                fake = _AssetsVLLM(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "assets": [
                                                {
                                                    "existing_id": fixture["asset_ids"][0],
                                                    "type": "character",
                                                    "name": "林夏",
                                                    "description": "企图改写但必须复用",
                                                },
                                                {
                                                    "existing_id": None,
                                                    "type": "character",
                                                    "name": "新增人物",
                                                    "description": "新候选",
                                                },
                                            ]
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    }
                )
                await _run_assets_task(task_id, fake, monkeypatch, session_factory)
                after_assets = await _read_project_assets(fixture["project_id"])
                assert after_assets[:-1] == before_assets
                assert after_assets[-1][2:5] == ("新增人物", "新候选", "generated")
                assert await _read_replace_structure(fixture) == before_structure
                assert await _read_episode_markers(fixture["target_episode_id"]) == (4, 4, None)
                assert fake.wake_calls == 1 and fake.chat_calls == 1
            finally:
                await _cleanup_replace_fixture(fixture, task_ids)
                await isolated_engine.dispose()
        asyncio.run(run())
        return

    if row == "regenerate_shots":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory)
            success_fixture = await _create_replace_fixture(tmp_path / "shots-success")
            monkeypatch.setattr(settings, "DATA_DIR", success_fixture["data_dir"])
            success_tasks: list[int] = []
            try:
                before_other = (await _read_replace_structure(success_fixture))[1]
                task_id = await insert_shot_task(
                    _replace_payload(success_fixture),
                    success_fixture["target_episode_id"],
                    session_factory,
                )
                success_tasks.append(task_id)
                fake = _ShotsVLLM(
                    shot_response(
                        {
                            "shots": [
                                _shot(order=1, asset_ids=success_fixture["asset_ids"][:2]),
                                _shot(order=2, asset_ids=[success_fixture["asset_ids"][2]]),
                            ]
                        }
                    )
                )
                monkeypatch.setattr("app.tasks.gen_shots.VLLMClient", lambda _url: fake)
                await run_shot_task(task_id, session_factory)
                status, error = await _read_task(task_id)
                assert status == "done", error
                after_target, after_other = await _read_replace_structure(success_fixture)
                assert after_other == before_other
                assert after_target["marker"] == success_fixture["script_revision"]
                assert len(after_target["shots"]) == 2
                assert [row["description"] for row in after_target["shots"]] == [
                    "人物站在站台边缘，雨水沿着伞面滑落",
                    "人物站在站台边缘，雨水沿着伞面滑落",
                ]
                assert [row["dialogue"] for row in after_target["shots"]] == ["", ""]
                assert after_target["shot_assets"] == [
                    {"shot_id": after_target["shots"][0]["id"], "asset_id": success_fixture["asset_ids"][0]},
                    {"shot_id": after_target["shots"][0]["id"], "asset_id": success_fixture["asset_ids"][1]},
                    {"shot_id": after_target["shots"][1]["id"], "asset_id": success_fixture["asset_ids"][2]},
                ]
                assert after_target["clips"] == []
                assert after_target["clip_videos"] == []
                for media in success_fixture["target_media"]:
                    source = tmp_path / "shots-success" / Path(media["path"])
                    trash = tmp_path / "shots-success" / "trash" / Path(media["path"])
                    assert not source.exists()
                    assert trash.read_bytes() == f"media-{media['id']}".encode()
                assert fake.wake_calls == 1 and fake.chat_calls == 1
            finally:
                await _cleanup_replace_fixture(success_fixture, success_tasks)

            failure_fixture = await _create_replace_fixture(tmp_path / "shots-failure")
            monkeypatch.setattr(settings, "DATA_DIR", failure_fixture["data_dir"])
            failure_tasks: list[int] = []
            try:
                before_target, before_other = await _read_replace_structure(failure_fixture)
                before_bytes = {
                    media["path"]: (tmp_path / "shots-failure" / Path(media["path"])).read_bytes()
                    for media in failure_fixture["target_media"]
                }
                task_id = await insert_shot_task(
                    _replace_payload(failure_fixture),
                    failure_fixture["target_episode_id"],
                    session_factory,
                )
                failure_tasks.append(task_id)
                fake = _ShotsVLLM(error=RuntimeError("controlled model failure"))
                monkeypatch.setattr("app.tasks.gen_shots.VLLMClient", lambda _url: fake)
                await run_shot_task(task_id, session_factory)
                status, error = await _read_task(task_id)
                assert status == "failed" and error is not None
                assert "controlled model failure" in error
                assert await _read_replace_structure(failure_fixture) == (before_target, before_other)
                for path, content in before_bytes.items():
                    assert (tmp_path / "shots-failure" / Path(path)).read_bytes() == content
                    assert not (tmp_path / "shots-failure" / "trash" / Path(path)).exists()
                assert fake.wake_calls == 1 and fake.chat_calls == 1
            finally:
                await _cleanup_replace_fixture(failure_fixture, failure_tasks)
                await isolated_engine.dispose()
        asyncio.run(run())
        return

    if row == "edit_asset":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory, idle_worker=True)
            fixture = await create_video_fixture(tmp_path)
            try:
                with TestClient(app) as client:
                    before = await _read_asset_edit_state(fixture)
                    renamed = client.patch(
                        f"/api/assets/{fixture['character_id']}",
                        json={"name": "林夏改名"},
                    )
                    assert renamed.status_code == 200
                    after_name = await _read_asset_edit_state(fixture)
                    assert after_name["asset"] == ("林夏改名", before["asset"][1], before["asset"][2] + 1)
                    assert [row[1] for row in after_name["shots"]] == ["changed", "changed"]
                    assert [row[2] for row in after_name["shots"]] == [row[2] + 1 for row in before["shots"]]
                    assert after_name["clips"] == [(fixture["clip_id"], "stale", before["clips"][0][2])]
                    assert after_name["images"] == before["images"]

                    no_op = client.patch(
                        f"/api/assets/{fixture['character_id']}",
                        json={"name": "林夏改名"},
                    )
                    assert no_op.status_code == 200
                    after_no_op = await _read_asset_edit_state(fixture)
                    assert after_no_op["asset"][2] == after_name["asset"][2]
                    assert after_no_op["shots"] == after_name["shots"]
                    assert after_no_op["clips"] == after_name["clips"]

                    described = client.patch(
                        f"/api/assets/{fixture['character_id']}",
                        json={"description": "新的描述"},
                    )
                    assert described.status_code == 200
                    after_description = await _read_asset_edit_state(fixture)
                    assert after_description["asset"] == ("林夏改名", "新的描述", before["asset"][2] + 2)

                    image_id = await _add_second_image(fixture, tmp_path)
                    switched = client.put(
                        f"/api/assets/{fixture['character_id']}/current-image",
                        json={"image_id": image_id},
                    )
                    assert switched.status_code == 200
                    after_current = await _read_asset_edit_state(fixture)
                    assert after_current["asset"][2] == before["asset"][2] + 3
                    assert sum(1 for image in after_current["images"] if image[3]) == 1
                    assert next(image for image in after_current["images"] if image[0] == image_id)[3] is True
                    assert [row[1] for row in after_current["shots"]] == ["changed", "changed"]
                    assert after_current["clips"][0][1] == "stale"
            finally:
                await cleanup_video_fixture(fixture)
        asyncio.run(run())
        return

    if row == "delete_asset":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory, idle_worker=True)
            fixture = await create_asset_fixture(tmp_path)
            try:
                before = await read_asset_state(fixture)
                with TestClient(app) as client:
                    response = client.delete(f"/api/assets/{fixture['target_asset_id']}")
                assert response.status_code == 204
                after = await read_asset_state(fixture)
                assert after["asset_exists"] is False and after["target_image_exists"] is False
                assert after["shot_assets"] == [
                    {
                        "shot_id": fixture["shot_other_id"],
                        "asset_id": fixture["other_asset_id"],
                    }
                ]
                assert after["clips"] == [
                    {**before["clips"][0], "freshness": "stale"},
                    {**before["clips"][1], "freshness": "stale"},
                    before["clips"][2],
                ]
                assert after["slots"][0]["asset_id"] is None
                assert after["slots"][1]["asset_id"] is None
                assert after["slots"][1]["override_image_path"] == fixture["override_path"]
                assert (tmp_path / "trash" / Path(fixture["target_image_path"])).read_bytes() == b"target asset image"
                assert (tmp_path / Path(fixture["override_path"])).read_bytes() == b"slot override remains"
            finally:
                await cleanup_asset_fixture(fixture)
        asyncio.run(run())
        return

    if row == "edit_shot_binding":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory, idle_worker=True)
            fixture = await create_video_fixture(tmp_path)
            try:
                with TestClient(app) as client:
                    before = await _read_asset_edit_state(fixture)
                    text_change = client.patch(
                        f"/api/shots/{fixture['shot_ids'][0]}",
                        json={"description": "新的镜头文本"},
                    )
                    assert text_change.status_code == 200
                    changed = await _read_asset_edit_state(fixture)
                    assert changed["shots"][0][2] == before["shots"][0][2] + 1
                    assert changed["shots"][0][1] == "changed"
                    assert changed["clips"][0][1] == "stale"
                    binding_change = client.patch(
                        f"/api/shots/{fixture['shot_ids'][1]}",
                        json={"asset_ids": [fixture["character_id"]]},
                    )
                    assert binding_change.status_code == 200
                    deleted_binding = client.patch(
                        f"/api/shots/{fixture['shot_ids'][1]}",
                        json={"asset_ids": []},
                    )
                    assert deleted_binding.status_code == 200
                    after = await _read_asset_edit_state(fixture)
                    assert after["shots"][1][2] == before["shots"][1][2] + 2
                    assert after["shots"][1][1] == "changed"
                    assert after["clips"][0][1] == "stale"
            finally:
                await cleanup_video_fixture(fixture)
        asyncio.run(run())
        return

    if row == "edit_style_template":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            fixture = await create_video_fixture(tmp_path)
            task_ids: list[int] = []
            try:
                before = await _read_asset_edit_state(fixture)
                async with session_factory() as session:
                    await update_style(
                        session,
                        fixture["style_id"],
                        StylePatch(prompt_fragment="新风格提示"),
                    )
                async with session_factory() as session:
                    await update_prompt_template(
                        session,
                        "minimaxh3",
                        PromptTemplatePatch(
                            content=(
                                "changed={{shots}}|{{references}}|{{style}}|"
                                "{{requested_duration}}|{{user_note}}"
                            )
                        ),
                    )
                assert await _read_asset_edit_state(fixture) == before
                from app.integrations.workflow_binding import load_minimax_binding_snapshot

                queue = TaskQueue(session_factory)
                async with session_factory() as session:
                    result = await enqueue_generate_clip_video(
                        session,
                        queue,
                        fixture["clip_id"],
                        user_note=None,
                        user_note_provided=False,
                        request_id=None,
                        workflow_binding=load_minimax_binding_snapshot(),
                    )
                task_ids.append(int(result.task.id))
                connection = await asyncpg.connect(_database_url())
                try:
                    row_data = await connection.fetchrow(
                        "SELECT payload FROM tasks WHERE id = $1", result.task.id
                    )
                    assert row_data is not None
                    payload = row_data["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    assert isinstance(payload, dict)
                    snapshot = payload["input_snapshot"]
                    assert snapshot["template_content"].startswith("changed=")
                    assert snapshot["style"] == "新风格提示"
                    assert payload["input_hash"] is not None
                finally:
                    await connection.close()
            finally:
                await cleanup_video_fixture(fixture)
                await isolated_engine.dispose()
        asyncio.run(run())
        return

    if row == "delete_clip":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory, idle_worker=True)
            fixture = await _create_replace_fixture(tmp_path)
            try:
                target_clip_id = fixture["target_clip_ids"][0]
                expected_media: dict[str, bytes] = {}
                for media in fixture["target_media"]:
                    content = (
                        b"clip to delete"
                        if media is fixture["target_media"][0]
                        else f"media-{media['id']}".encode()
                    )
                    (tmp_path / Path(media["path"])).write_bytes(content)
                    expected_media[media["path"]] = content
                await _synchronize_slot_override_digests(fixture, tmp_path)
                _, before_other = await _read_replace_structure(fixture)
                with TestClient(app) as client:
                    response = client.delete(f"/api/clips/{target_clip_id}")
                assert response.status_code == 204
                target, other = await _read_replace_structure(fixture)
                assert all(item["id"] != target_clip_id for item in target["clips"])
                assert len(target["clips"]) == 1
                assert len(target["shots"]) == 2
                assert len(target["clip_videos"]) == 1
                assert len(target["clip_ref_slots"]) == 1
                assert other == before_other
                for media in fixture["target_media"]:
                    if f"/clips/{target_clip_id}/" not in media["path"]:
                        continue
                    source = tmp_path / Path(media["path"])
                    trash = tmp_path / "trash" / Path(media["path"])
                    assert not source.exists()
                    assert trash.read_bytes() == expected_media[media["path"]]
            finally:
                await _cleanup_replace_fixture(fixture, [])
        asyncio.run(run())
        return

    if row == "clip_success":
        async def run() -> None:
            isolated_engine, session_factory = _isolated_engine()
            _patch_runtime(monkeypatch, isolated_engine, session_factory)
            fixture = await create_video_fixture(tmp_path)
            try:
                queue, task = await _enqueue_and_claim_with_factory(fixture, session_factory)
                temp_path, raw = _write_temp(tmp_path, task)
                async with session_factory() as session:
                    completed = await commit_generated_clip_video(
                        session,
                        queue,
                        task,
                        GeneratedClipVideo(
                            temp_path=temp_path,
                            built_prompt="C012 committed prompt",
                        ),
                        data_dir=tmp_path,
                    )
                assert completed is not None and completed.changed
                state = await _read_commit_state(fixture)
                assert state["clip"]["freshness"] == "fresh"
                assert state["clip"]["generation_state"] == "ready"
                assert [row["status"] for row in state["shots"]] == ["normal", "normal"]
                assert len(state["videos"]) == 1
                video = state["videos"][0]
                relative, formal, trash = clip_video_paths(
                    tmp_path,
                    fixture["project_id"],
                    fixture["episode_id"],
                    fixture["clip_id"],
                    video["id"],
                )
                assert video["file_path"] == relative.as_posix()
                assert formal.read_bytes() == raw
                assert not temp_path.exists() and not trash.exists()
                assert video["is_current"] is True
                assert state["tasks"][0]["status"] == "done"
            finally:
                await cleanup_video_fixture(fixture)
                await isolated_engine.dispose()
        asyncio.run(run())
        return

    raise AssertionError(row)


def test_c012_cascade_regenerate_assets_failure_preserves_structure_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        isolated_engine, session_factory = _isolated_engine()
        _patch_runtime(monkeypatch, isolated_engine, session_factory)
        fixture = await _create_replace_fixture(tmp_path)
        task_ids: list[int] = []
        try:
            before_structure = await _read_replace_structure(fixture)
            before_assets = await _read_project_assets(fixture["project_id"])
            before_markers = await _read_episode_markers(fixture["target_episode_id"])
            before_bytes = {
                media["path"]: (tmp_path / Path(media["path"])).read_bytes()
                for media in fixture["target_media"]
            }
            task_id = await _insert_task(
                task_type="gen_assets",
                target_id=fixture["target_episode_id"],
                payload={
                    "input_snapshot": {
                        "episode_id": fixture["target_episode_id"],
                        "project_id": fixture["project_id"],
                        "script": "目标剧本",
                        "script_revision": fixture["script_revision"],
                        "rendered_prompt": "R2 failure",
                        "model": "controlled-model",
                        "temperature": 0.2,
                    },
                    "input_hash": None,
                    "source_revisions": {},
                },
                session_factory=session_factory,
            )
            task_ids.append(task_id)
            fake = _FailingAssetsVLLM(RuntimeError("controlled model failure"))
            monkeypatch.setattr("app.tasks.gen_assets.VLLMClient", lambda _url: fake)
            await TaskQueue(session_factory).run_worker(
                handlers={"gen_assets": gen_assets_handler},
                poll_interval=0.01,
                stop_when_idle=True,
            )
            status, error = await _read_task(task_id)
            assert status == "failed"
            assert error is not None and "controlled model failure" in error
            assert await _read_replace_structure(fixture) == before_structure
            assert await _read_project_assets(fixture["project_id"]) == before_assets
            assert await _read_episode_markers(fixture["target_episode_id"]) == before_markers
            for path, content in before_bytes.items():
                assert (tmp_path / Path(path)).read_bytes() == content
                assert not (tmp_path / "trash" / Path(path)).exists()
            assert fake.wake_calls == 1 and fake.chat_calls == 1
        finally:
            await _cleanup_replace_fixture(fixture, task_ids)
            await isolated_engine.dispose()

    asyncio.run(run())
