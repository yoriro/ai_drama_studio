from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import asyncpg
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.api import assets as assets_api
from app.db.session import async_session_factory, engine
from app.main import app
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.queue import (
    ClaimedTask,
    TaskChange,
    TaskConflictError,
    TaskQueue,
    WorkerContext,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _task_payload(
    episode_id: int,
    project_id: int,
    script_revision: int,
) -> dict[str, object]:
    return {
        "input_snapshot": {
            "episode_id": episode_id,
            "project_id": project_id,
            "script": "C012 race script",
            "script_revision": script_revision,
            "style": "C012 race style",
            "template_key": "script2assets",
            "template_content": "C012 race template",
            "existing_assets": [],
            "rendered_prompt": "C012 race rendered prompt",
            "model": "C012 race model",
            "temperature": 0.2,
        },
        "input_hash": None,
        "source_revisions": {
            "episode": {"id": episode_id, "script_revision": script_revision},
            "assets": [],
        },
    }


async def _create_fixture(
    *,
    marker: int = 3,
    asset_names: tuple[str, ...] = ("原资产",),
    with_downstream: bool = False,
) -> dict[str, int | list[int]]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            f"C012 race style {suffix}",
            "C012 race style prompt",
        )
        project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            f"C012 race project {suffix}",
            style_id,
        )
        episode_id = await connection.fetchval(
            "INSERT INTO episodes "
            "(project_id, seq, title, script_text, assets_generated_script_revision) "
            "VALUES ($1, 1, 'C012 race episode', 'C012 race script', $2) RETURNING id",
            project_id,
            marker,
        )
        asset_ids: list[int] = []
        for index, name in enumerate(asset_names, start=1):
            asset_id = await connection.fetchval(
                "INSERT INTO assets "
                "(project_id, type, name, description, source, revision) "
                "VALUES ($1, $2, $3, $4, 'manual', 1) RETURNING id",
                project_id,
                "character" if index % 2 else "scene",
                name,
                f"C012 original asset {index}",
            )
            asset_ids.append(int(asset_id))

        shot_id: int | None = None
        clip_id: int | None = None
        if with_downstream:
            if not asset_ids:
                raise AssertionError("downstream fixture requires an asset")
            shot_id = int(
                await connection.fetchval(
                    "INSERT INTO shots "
                    "(episode_id, order_index, duration_est, shot_type, camera, "
                    "description, dialogue, status, revision) "
                    "VALUES ($1, 1, 5.0, 'wide', 'fixed', 'C012 race shot', '', "
                    "'normal', 1) RETURNING id",
                    episode_id,
                )
            )
            clip_id = int(
                await connection.fetchval(
                    "INSERT INTO clips "
                    "(episode_id, requested_duration, generation_state, freshness, revision) "
                    "VALUES ($1, 5, 'ready', 'fresh', 1) RETURNING id",
                    episode_id,
                )
            )
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                shot_id,
                asset_ids[0],
            )
            await connection.execute(
                "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
                clip_id,
                shot_id,
            )
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "episode_id": int(episode_id),
            "asset_ids": asset_ids,
            "shot_id": -1 if shot_id is None else shot_id,
            "clip_id": -1 if clip_id is None else clip_id,
        }
    finally:
        await connection.close()


async def _insert_task(
    episode_id: int,
    project_id: int,
    *,
    marker: int,
    status: str = "queued",
) -> tuple[int, dict[str, object]]:
    payload = _task_payload(episode_id, project_id, marker)
    connection = await asyncpg.connect(_database_url())
    try:
        task_id = await connection.fetchval(
            "INSERT INTO tasks (type, target_id, payload, status, progress) "
            "VALUES ('gen_assets', $1, $2::jsonb, $3, 0) RETURNING id",
            episode_id,
            json.dumps(payload, ensure_ascii=False),
            status,
        )
        return int(task_id), payload
    finally:
        await connection.close()


async def _read_assets(project_id: int) -> list[tuple[object, ...]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            "SELECT id, type, name, description, source, revision "
            "FROM assets WHERE project_id = $1 ORDER BY id",
            project_id,
        )
        return [tuple(row) for row in rows]
    finally:
        await connection.close()


async def _read_task_state(
    task_id: int,
    episode_id: int,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    connection = await asyncpg.connect(_database_url())
    try:
        task = await connection.fetchrow(
            "SELECT status, cancel_requested_at, error_msg FROM tasks WHERE id = $1",
            task_id,
        )
        episode = await connection.fetchrow(
            "SELECT assets_generated_script_revision FROM episodes WHERE id = $1",
            episode_id,
        )
        if task is None or episode is None:
            raise AssertionError("C012 race task or episode disappeared")
        return tuple(task), tuple(episode)
    finally:
        await connection.close()


async def _read_downstream(
    episode_id: int,
    shot_id: int,
    clip_id: int,
) -> tuple[
    tuple[object, ...],
    tuple[object, ...],
    tuple[object, ...],
    list[tuple[object, ...]],
    list[tuple[object, ...]],
]:
    connection = await asyncpg.connect(_database_url())
    try:
        episode = await connection.fetchrow(
            "SELECT id, script_revision, assets_generated_script_revision "
            "FROM episodes WHERE id = $1",
            episode_id,
        )
        shot = await connection.fetchrow(
            "SELECT id, status, revision, description FROM shots WHERE id = $1",
            shot_id,
        )
        clip = await connection.fetchrow(
            "SELECT id, generation_state, freshness, revision FROM clips WHERE id = $1",
            clip_id,
        )
        shot_assets = await connection.fetch(
            "SELECT shot_id, asset_id FROM shot_assets WHERE shot_id = $1",
            shot_id,
        )
        clip_shots = await connection.fetch(
            "SELECT clip_id, shot_id, position FROM clip_shots WHERE clip_id = $1",
            clip_id,
        )
        if episode is None or shot is None or clip is None:
            raise AssertionError("C012 downstream fixture disappeared")
        return (
            tuple(episode),
            tuple(shot),
            tuple(clip),
            [tuple(row) for row in shot_assets],
            [tuple(row) for row in clip_shots],
        )
    finally:
        await connection.close()


async def _cleanup_fixture(
    fixture: dict[str, int | list[int]],
    task_ids: list[int] | None = None,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        shot_id = int(fixture["shot_id"])
        clip_id = int(fixture["clip_id"])
        if clip_id > 0:
            await connection.execute(
                "DELETE FROM clip_shots WHERE clip_id = $1", clip_id
            )
            await connection.execute("DELETE FROM clips WHERE id = $1", clip_id)
        if shot_id > 0:
            await connection.execute(
                "DELETE FROM shot_assets WHERE shot_id = $1", shot_id
            )
            await connection.execute("DELETE FROM shots WHERE id = $1", shot_id)
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", int(fixture["episode_id"])
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", int(fixture["project_id"])
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", int(fixture["project_id"])
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", int(fixture["style_id"])
        )
    finally:
        await connection.close()


class _ControlledVLLM:
    response: dict[str, object] = {}
    wake_calls = 0
    chat_calls = 0

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def wake(self) -> None:
        type(self).wake_calls += 1

    async def structured_chat(self, **request: Any) -> dict[str, object]:
        del request
        type(self).chat_calls += 1
        return type(self).response


class _CommitGate:
    def __init__(self, original_exit: Any) -> None:
        self.original_exit = original_exit
        self.session_ids: set[int] = set()
        self.entered = asyncio.Event()
        self.allow = asyncio.Event()
        self.claimed = False
        self.wait_observation: dict[str, object] | None = None

    def mark(self, session: AsyncSession) -> None:
        self.session_ids.add(id(session))

    async def exit(
        self,
        transaction: AsyncSessionTransaction,
        type_: Any,
        value: Any,
        traceback: Any,
    ) -> None:
        if (
            type_ is None
            and id(transaction.session) in self.session_ids
            and not self.claimed
        ):
            self.claimed = True
            self.entered.set()
            await self.allow.wait()
        await self.original_exit(transaction, type_, value, traceback)


async def _wait_for_asset_lock() -> dict[str, object]:
    for _ in range(500):
        connection = await asyncpg.connect(_database_url())
        try:
            row = await connection.fetchrow(
                "SELECT pid, wait_event_type, wait_event, query "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() "
                "AND state = 'active' "
                "AND wait_event_type = 'Lock' "
                "AND query ILIKE '%assets%' "
                "AND query NOT ILIKE '%pg_stat_activity%' "
                "ORDER BY pid LIMIT 1"
            )
        finally:
            await connection.close()
        if row is not None:
            return dict(row)
        await asyncio.sleep(0.01)
    raise AssertionError("C012 name race did not expose a PostgreSQL lock wait")


async def _api_request(
    method: str,
    path: str,
    payload: dict[str, object],
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://c012.test") as client:
        return await client.request(method, path, json=payload)


async def _run_api_race(
    monkeypatch: Any,
    service_name: str,
    requests: list[tuple[str, str, dict[str, object]]],
) -> tuple[list[httpx.Response], dict[str, object]]:
    gate = _CommitGate(AsyncSessionTransaction.__aexit__)
    original_service = getattr(assets_api, service_name)

    async def marked_service(session: AsyncSession, *args: object, **kwargs: object) -> object:
        gate.mark(session)
        return await original_service(session, *args, **kwargs)

    async def gated_exit(
        transaction: AsyncSessionTransaction,
        type_: Any,
        value: Any,
        traceback: Any,
    ) -> None:
        await gate.exit(transaction, type_, value, traceback)

    with monkeypatch.context() as patch:
        patch.setattr(assets_api, service_name, marked_service)
        patch.setattr(AsyncSessionTransaction, "__aexit__", gated_exit)
        pending = [
            asyncio.create_task(_api_request(method, path, payload))
            for method, path, payload in requests
        ]
        try:
            await asyncio.wait_for(gate.entered.wait(), timeout=5)
            gate.wait_observation = await _wait_for_asset_lock()
        finally:
            gate.allow.set()
        responses = await asyncio.gather(*pending)
    if gate.wait_observation is None:
        raise AssertionError("C012 API race lost its lock observation")
    return responses, gate.wait_observation


def _response_body(response: httpx.Response) -> object:
    return response.json()


def _generated_response(
    *,
    asset_type: str,
    name: str,
    description: str,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "assets": [
                                {
                                    "existing_id": None,
                                    "type": asset_type,
                                    "name": name,
                                    "description": description,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


async def _run_generation_worker() -> None:
    await TaskQueue(async_session_factory).run_worker(
        handlers={"gen_assets": gen_assets_handler},
        stop_when_idle=True,
        poll_interval=0.01,
    )


async def _run_claimed_handler(
    queue: TaskQueue,
    task_id: int,
    episode_id: int,
    payload: dict[str, object],
) -> None:
    claimed = ClaimedTask(
        id=task_id,
        type="gen_assets",
        target_id=episode_id,
        request_id=None,
        payload=payload,
    )
    await gen_assets_handler(
        claimed,
        WorkerContext(queue, claimed, async_session_factory),
    )


class _AtomicCommitQueue(TaskQueue):
    def __init__(self) -> None:
        super().__init__(async_session_factory)
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()
        self.business_committed = asyncio.Event()

    async def complete(self, session: AsyncSession, task_id: int) -> TaskChange:
        self.complete_entered.set()
        await self.allow_complete.wait()
        return await super().complete(session, task_id)

    async def publish_committed(
        self,
        result: TaskChange,
        publisher: Any = None,
    ) -> None:
        await super().publish_committed(result, publisher)
        if result.event is not None and result.event.status == "done":
            self.business_committed.set()


async def _request_cancel(task_id: int) -> TaskChange:
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.request_cancel(session, task_id)


async def _request_cancel_after_done(task_id: int) -> None:
    queue = TaskQueue(async_session_factory)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await queue.request_cancel(session, task_id)
    except TaskConflictError as exc:
        assert exc.conflict_kind == "terminal_cancel"
        return
    raise AssertionError("cancel after done did not produce a terminal conflict")


def test_c012_api_name_races_have_one_winner_and_exact_conflict(monkeypatch) -> None:
    async def run() -> None:
        create_fixture = await _create_fixture(asset_names=())
        rename_fixture = await _create_fixture(
            asset_names=("改名前一", "改名前二")
        )
        try:
            create_path = f"/api/projects/{create_fixture['project_id']}/assets"
            create_responses, create_wait = await _run_api_race(
                monkeypatch,
                "create_asset",
                [
                    (
                        "POST",
                        create_path,
                        {
                            "type": "character",
                            "name": "API 创建竞争",
                            "description": "manual winner candidate",
                        },
                    ),
                    (
                        "POST",
                        create_path,
                        {
                            "type": "scene",
                            "name": " API 创建竞争 ",
                            "description": "conflicting candidate",
                        },
                    ),
                ],
            )
            assert sorted(response.status_code for response in create_responses) == [
                201,
                409,
            ]
            assert sum(response.status_code == 201 for response in create_responses) == 1
            assert [
                _response_body(response)
                for response in create_responses
                if response.status_code == 409
            ] == [
                {"detail": {"code": "conflict", "message": "资产名称已存在"}}
            ]
            create_rows = await _read_assets(int(create_fixture["project_id"]))
            assert [row[2] for row in create_rows] == ["API 创建竞争"]
            assert create_rows[0][1] in {"character", "scene"}
            assert create_rows[0][4:] == ("manual", 1)

            rename_path = f"/api/assets/{rename_fixture['asset_ids'][0]}"
            rename_path_two = f"/api/assets/{rename_fixture['asset_ids'][1]}"
            rename_responses, rename_wait = await _run_api_race(
                monkeypatch,
                "update_asset",
                [
                    ("PATCH", rename_path, {"name": "API 改名竞争"}),
                    ("PATCH", rename_path_two, {"name": " API 改名竞争 "}),
                ],
            )
            assert sorted(response.status_code for response in rename_responses) == [
                200,
                409,
            ]
            assert [
                _response_body(response)
                for response in rename_responses
                if response.status_code == 409
            ] == [
                {"detail": {"code": "conflict", "message": "资产名称已存在"}}
            ]
            rename_rows = await _read_assets(int(rename_fixture["project_id"]))
            assert [row[2] for row in rename_rows].count("API 改名竞争") == 1
            assert sorted(row[5] for row in rename_rows) == [1, 2]
            print(
                "C012 API name race observations "
                + json.dumps(
                    {
                        "create_lock": create_wait,
                        "create_statuses": sorted(
                            response.status_code for response in create_responses
                        ),
                        "create_rows": create_rows,
                        "rename_lock": rename_wait,
                        "rename_statuses": sorted(
                            response.status_code for response in rename_responses
                        ),
                        "rename_rows": rename_rows,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
        finally:
            await _cleanup_fixture(create_fixture)
            await _cleanup_fixture(rename_fixture)
            await engine.dispose()

    asyncio.run(run())


async def _run_manual_generation_race(
    monkeypatch: Any,
    *,
    generation_wins: bool,
    generation_type: str,
    manual_type: str,
) -> tuple[dict[str, object], dict[str, object]]:
    import app.tasks.gen_assets as gen_assets_module

    fixture = await _create_fixture(marker=13, with_downstream=True)
    task_id, payload = await _insert_task(
        int(fixture["episode_id"]),
        int(fixture["project_id"]),
        marker=13,
    )
    baseline_downstream = await _read_downstream(
        int(fixture["episode_id"]),
        int(fixture["shot_id"]),
        int(fixture["clip_id"]),
    )
    name = "手动生成竞争"
    original_exit = AsyncSessionTransaction.__aexit__
    original_merge = gen_assets_module._merge_generated_assets
    original_create = assets_api.create_asset
    gate = _CommitGate(original_exit)
    _ControlledVLLM.response = _generated_response(
        asset_type=generation_type,
        name=name,
        description="generated race candidate",
    )
    _ControlledVLLM.wake_calls = 0
    _ControlledVLLM.chat_calls = 0

    async def marked_merge(
        session: AsyncSession,
        task: ClaimedTask,
        result: Any,
    ) -> None:
        await original_merge(session, task, result)
        if generation_wins:
            gate.mark(session)

    async def marked_create(
        session: AsyncSession,
        project_id: int,
        payload: Any,
    ) -> Any:
        if not generation_wins:
            gate.mark(session)
        return await original_create(session, project_id, payload)

    async def gated_exit(
        transaction: AsyncSessionTransaction,
        type_: Any,
        value: Any,
        traceback: Any,
    ) -> None:
        await gate.exit(transaction, type_, value, traceback)

    observations: dict[str, object]
    try:
        with monkeypatch.context() as patch:
            patch.setattr(gen_assets_module, "VLLMClient", _ControlledVLLM)
            patch.setattr(gen_assets_module, "_merge_generated_assets", marked_merge)
            patch.setattr(assets_api, "create_asset", marked_create)
            patch.setattr(AsyncSessionTransaction, "__aexit__", gated_exit)
            worker = asyncio.create_task(_run_generation_worker())
            if generation_wins:
                await asyncio.wait_for(gate.entered.wait(), timeout=5)
                manual = asyncio.create_task(
                    _api_request(
                        "POST",
                        f"/api/projects/{fixture['project_id']}/assets",
                        {
                            "type": manual_type,
                            "name": f" {name} ",
                            "description": "manual race candidate",
                        },
                    )
                )
            else:
                manual = asyncio.create_task(
                    _api_request(
                        "POST",
                        f"/api/projects/{fixture['project_id']}/assets",
                        {
                            "type": manual_type,
                            "name": f" {name} ",
                            "description": "manual race candidate",
                        },
                    )
                )
                await asyncio.wait_for(gate.entered.wait(), timeout=5)
            gate.wait_observation = await _wait_for_asset_lock()
            gate.allow.set()
            manual_response, _ = await asyncio.gather(manual, worker)
            task_state, episode_state = await _read_task_state(
                task_id, int(fixture["episode_id"])
            )
            assets = await _read_assets(int(fixture["project_id"]))
            downstream = await _read_downstream(
                int(fixture["episode_id"]),
                int(fixture["shot_id"]),
                int(fixture["clip_id"]),
            )
            assert downstream == baseline_downstream
            if generation_wins:
                assert manual_response.status_code == 409
                assert _response_body(manual_response) == {
                    "detail": {"code": "conflict", "message": "资产名称已存在"}
                }
                assert task_state[0] == "done"
                assert episode_state == (13,)
                assert len(assets) == 2
                assert assets[-1][1:] == (
                    generation_type,
                    name,
                    "generated race candidate",
                    "generated",
                    1,
                )
            else:
                assert manual_response.status_code == 201
                assert task_state[0] == "failed"
                assert task_state[2] is not None
                assert "normalized asset name conflicts across asset types" in str(
                    task_state[2]
                )
                assert episode_state == (13,)
                assert len(assets) == 2
                assert assets[-1][1:] == (
                    manual_type,
                    name,
                    "manual race candidate",
                    "manual",
                    1,
                )
            assert _ControlledVLLM.wake_calls == 1
            assert _ControlledVLLM.chat_calls == 1
            observations = {
                "lock": gate.wait_observation,
                "manual_status": manual_response.status_code,
                "task": task_state,
                "episode": episode_state,
                "assets": assets,
            }
    finally:
        gate.allow.set()
        await _cleanup_fixture(fixture, [task_id])
        await engine.dispose()
    return observations, {"fixture": fixture}


def test_c012_manual_generation_races_converge_by_unique_name(monkeypatch) -> None:
    async def run() -> None:
        generation_wins, _ = await _run_manual_generation_race(
            monkeypatch,
            generation_wins=True,
            generation_type="character",
            manual_type="character",
        )
        manual_wins, _ = await _run_manual_generation_race(
            monkeypatch,
            generation_wins=False,
            generation_type="scene",
            manual_type="character",
        )
        print(
            "C012 manual-generation race observations "
            + json.dumps(
                {"generation_wins": generation_wins, "manual_wins": manual_wins},
                ensure_ascii=False,
                default=str,
            )
        )

    asyncio.run(run())


def test_c012_gen_assets_cancel_and_done_keep_marker_atomic(monkeypatch) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        monkeypatch.setattr(gen_assets_module, "VLLMClient", _ControlledVLLM)
        try:
            cancel_fixture = await _create_fixture(marker=17, with_downstream=True)
            cancel_task_id, cancel_payload = await _insert_task(
                int(cancel_fixture["episode_id"]),
                int(cancel_fixture["project_id"]),
                marker=17,
                status="running",
            )
            try:
                _ControlledVLLM.response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "assets": [
                                            {
                                                "existing_id": None,
                                                "type": "character",
                                                "name": "取消批次一",
                                                "description": "取消后回滚一",
                                            },
                                            {
                                                "existing_id": None,
                                                "type": "scene",
                                                "name": "取消批次二",
                                                "description": "取消后回滚二",
                                            },
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
                _ControlledVLLM.wake_calls = 0
                _ControlledVLLM.chat_calls = 0
                queue = _AtomicCommitQueue()
                before = await _read_downstream(
                    int(cancel_fixture["episode_id"]),
                    int(cancel_fixture["shot_id"]),
                    int(cancel_fixture["clip_id"]),
                )
                handler = asyncio.create_task(
                    _run_claimed_handler(
                        queue,
                        cancel_task_id,
                        int(cancel_fixture["episode_id"]),
                        cancel_payload,
                    )
                )
                await asyncio.wait_for(queue.complete_entered.wait(), timeout=5)
                cancel_change = await _request_cancel(cancel_task_id)
                assert cancel_change.task is not None
                assert cancel_change.task.status == "running"
                assert cancel_change.task.cancel_requested_at is not None
                queue.allow_complete.set()
                await handler
                task_state, episode_state = await _read_task_state(
                    cancel_task_id, int(cancel_fixture["episode_id"])
                )
                assert task_state[0] == "canceled"
                assert task_state[1] is not None
                assert task_state[2] is None
                assert episode_state == (17,)
                cancel_assets = await _read_assets(int(cancel_fixture["project_id"]))
                assert [row[2] for row in cancel_assets] == ["原资产"]
                assert await _read_downstream(
                    int(cancel_fixture["episode_id"]),
                    int(cancel_fixture["shot_id"]),
                    int(cancel_fixture["clip_id"]),
                ) == before
                assert _ControlledVLLM.wake_calls == 1
                assert _ControlledVLLM.chat_calls == 1
            finally:
                await _cleanup_fixture(cancel_fixture, [cancel_task_id])

            done_fixture = await _create_fixture(marker=19, with_downstream=True)
            done_task_id, done_payload = await _insert_task(
                int(done_fixture["episode_id"]),
                int(done_fixture["project_id"]),
                marker=19,
                status="running",
            )
            try:
                queue = _AtomicCommitQueue()
                _ControlledVLLM.wake_calls = 0
                _ControlledVLLM.chat_calls = 0
                handler = asyncio.create_task(
                    _run_claimed_handler(
                        queue,
                        done_task_id,
                        int(done_fixture["episode_id"]),
                        done_payload,
                    )
                )
                await asyncio.wait_for(queue.complete_entered.wait(), timeout=5)
                queue.allow_complete.set()
                await asyncio.wait_for(queue.business_committed.wait(), timeout=5)
                await _request_cancel_after_done(done_task_id)
                await handler
                task_state, episode_state = await _read_task_state(
                    done_task_id, int(done_fixture["episode_id"])
                )
                assert task_state[0] == "done"
                assert task_state[1] is None
                assert task_state[2] is None
                assert episode_state == (19,)
                done_assets = await _read_assets(int(done_fixture["project_id"]))
                assert [row[2] for row in done_assets] == [
                    "原资产",
                    "取消批次一",
                    "取消批次二",
                ]
                assert [row[4] for row in done_assets[1:]] == [
                    "generated",
                    "generated",
                ]
                assert _ControlledVLLM.wake_calls == 1
                assert _ControlledVLLM.chat_calls == 1
            finally:
                await _cleanup_fixture(done_fixture, [done_task_id])
        finally:
            await engine.dispose()

        print(
            "C012 cancel/commit observations "
            + json.dumps(
                {
                    "cancel": {"status": "canceled", "marker": 17, "new_assets": 0},
                    "done": {"status": "done", "marker": 19, "new_assets": 2},
                    "vllm_wake_calls": _ControlledVLLM.wake_calls,
                    "vllm_chat_calls": _ControlledVLLM.chat_calls,
                },
                ensure_ascii=False,
            )
        )

    asyncio.run(run())
