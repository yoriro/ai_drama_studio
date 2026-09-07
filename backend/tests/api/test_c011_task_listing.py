import asyncio
import json
import os
import time

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _seed_listing_tasks() -> list[int]:
    payload = json.dumps(
        {"input_snapshot": {}, "input_hash": None, "source_revisions": {}}
    )
    connection = await asyncpg.connect(_database_url())
    try:
        task_ids: list[int] = []
        groups = (
            (60, "gen_assets", "failed", 0.0),
            (10, "gen_shots", "canceled", 0.0),
            (10, "gen_asset_image", "queued", 0.0),
            (10, "gen_clip_video", "running", 0.2),
            (50, "gen_shots", "done", 1.0),
        )
        for count, task_type, status, progress in groups:
            for _ in range(count):
                row = await connection.fetchrow(
                    """
                    INSERT INTO tasks(type, target_id, payload, status, progress)
                    VALUES ($1, $2, $3::jsonb, $4, $5)
                    RETURNING id
                    """,
                    task_type,
                    1,
                    payload,
                    status,
                    progress,
                )
                assert row is not None
                task_ids.append(int(row["id"]))
        return task_ids
    finally:
        await connection.close()


async def _delete_listing_tasks(task_ids: list[int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids)
    finally:
        await connection.close()


def test_task_listing_filters_before_limit_and_validates_query() -> None:
    with TestClient(app) as client:
        app.state.task_worker_stop.set()
        time.sleep(0.1)
        task_ids = asyncio.run(_seed_listing_tasks())
        try:
            default_response = client.get("/api/tasks")
            assert default_response.status_code == 200
            default_ids = [item["id"] for item in default_response.json()]
            assert len(default_ids) == 50
            assert default_ids == list(reversed(task_ids[-50:]))

            maximum_response = client.get("/api/tasks?limit=100")
            assert maximum_response.status_code == 200
            maximum_ids = [item["id"] for item in maximum_response.json()]
            assert len(maximum_ids) == 100
            assert maximum_ids == list(reversed(task_ids[-100:]))

            failed_response = client.get("/api/tasks?status=failed&limit=20")
            assert failed_response.status_code == 200
            failed_items = failed_response.json()
            assert len(failed_items) == 20
            assert all(item["status"] == "failed" for item in failed_items)
            assert [item["id"] for item in failed_items] == list(
                reversed(task_ids[:60][-20:])
            )

            asset_type_response = client.get("/api/tasks?type=gen_assets&limit=100")
            assert asset_type_response.status_code == 200
            asset_type_items = asset_type_response.json()
            assert len(asset_type_items) == 60
            assert all(item["type"] == "gen_assets" for item in asset_type_items)
            assert [item["id"] for item in asset_type_items] == list(
                reversed(task_ids[:60])
            )

            combined_response = client.get(
                "/api/tasks?status=failed&type=gen_assets&limit=100"
            )
            assert combined_response.status_code == 200
            combined_items = combined_response.json()
            assert len(combined_items) == 60
            assert all(
                item["status"] == "failed" and item["type"] == "gen_assets"
                for item in combined_items
            )
            assert [item["id"] for item in combined_items] == list(
                reversed(task_ids[:60])
            )

            empty_response = client.get(
                "/api/tasks?status=queued&type=gen_assets&limit=100"
            )
            assert empty_response.status_code == 200
            assert empty_response.json() == []

            for query in (
                "limit=0",
                "limit=101",
                "status=unknown",
                "type=unknown",
            ):
                invalid_response = client.get(f"/api/tasks?{query}")
                assert invalid_response.status_code == 422
                assert invalid_response.json() == {
                    "detail": {
                        "code": "validation_error",
                        "message": "Request validation failed",
                    }
                }
        finally:
            asyncio.run(_delete_listing_tasks(task_ids))
