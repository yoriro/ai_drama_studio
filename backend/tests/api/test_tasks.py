import asyncio
import json
import time

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    import os

    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _seed_cancel_tasks() -> dict[str, int]:
    payload = json.dumps(
        {"input_snapshot": {}, "input_hash": None, "source_revisions": {}}
    )
    connection = await asyncpg.connect(_database_url())
    try:
        ids: dict[str, int] = {}
        for index, task_status in enumerate(
            ("queued", "running", "canceled", "done", "failed")
        ):
            progress = 0.2 if task_status == "running" else 1 if task_status == "done" else 0
            row = await connection.fetchrow(
                """
                INSERT INTO tasks(
                    type, target_id, payload, status, progress,
                    heartbeat_at, started_at, finished_at, error_msg
                ) VALUES (
                    'gen_assets', $1, $2, $3, $4,
                    CASE WHEN $5 THEN now() ELSE NULL END,
                    CASE WHEN $6 THEN now() ELSE NULL END,
                    CASE WHEN $7 THEN now() ELSE NULL END,
                    CASE WHEN $8 THEN 'seed failure' ELSE NULL END
                ) RETURNING id
                """,
                3_000_000 + index,
                payload,
                task_status,
                progress,
                task_status == "running",
                task_status == "running",
                task_status in {"canceled", "done", "failed"},
                task_status == "failed",
            )
            assert row is not None
            ids[task_status] = int(row["id"])
        return ids
    finally:
        await connection.close()


async def _delete_tasks(task_ids: list[int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids)
    finally:
        await connection.close()


def test_cancel_task_states() -> None:
    with TestClient(app) as client:
        app.state.task_worker_stop.set()
        time.sleep(0.1)
        task_ids = asyncio.run(_seed_cancel_tasks())
        try:
            queued = client.post(f"/api/tasks/{task_ids['queued']}/cancel")
            assert queued.status_code == 200
            assert queued.json()["status"] == "canceled"
            assert queued.json()["cancel_requested_at"] is None

            queued_repeat = client.post(
                f"/api/tasks/{task_ids['queued']}/cancel"
            )
            assert queued_repeat.status_code == 200
            assert queued_repeat.json()["status"] == "canceled"

            running = client.post(f"/api/tasks/{task_ids['running']}/cancel")
            assert running.status_code == 200
            assert running.json()["status"] == "running"
            assert running.json()["cancel_requested_at"] is not None

            running_repeat = client.post(
                f"/api/tasks/{task_ids['running']}/cancel"
            )
            assert running_repeat.status_code == 200
            assert running_repeat.json()["status"] == "running"

            canceled = client.post(f"/api/tasks/{task_ids['canceled']}/cancel")
            assert canceled.status_code == 200
            assert canceled.json()["status"] == "canceled"

            done = client.post(f"/api/tasks/{task_ids['done']}/cancel")
            assert done.status_code == 409
            assert done.json()["detail"]["code"] == "conflict"

            failed = client.post(f"/api/tasks/{task_ids['failed']}/cancel")
            assert failed.status_code == 409
            assert failed.json()["detail"]["code"] == "conflict"

            unknown = client.post("/api/tasks/2147483647/cancel")
            assert unknown.status_code == 404
            assert unknown.json()["detail"]["code"] == "not_found"

            body = client.post(
                f"/api/tasks/{task_ids['canceled']}/cancel", json={}
            )
            assert body.status_code == 422
            assert body.json()["detail"]["code"] == "validation_error"
        finally:
            asyncio.run(_delete_tasks(list(task_ids.values())))
