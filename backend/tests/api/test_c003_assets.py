import asyncio
import io
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _asset_image_paths(asset_id: int) -> list[str]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            "SELECT file_path FROM asset_images WHERE asset_id = $1 ORDER BY id",
            asset_id,
        )
        return [row["file_path"] for row in rows]
    finally:
        await connection.close()


async def _asset_and_image_counts(asset_id: int) -> tuple[int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset_count = await connection.fetchval(
            "SELECT count(*) FROM assets WHERE id = $1", asset_id
        )
        image_count = await connection.fetchval(
            "SELECT count(*) FROM asset_images WHERE asset_id = $1", asset_id
        )
        return int(asset_count), int(image_count)
    finally:
        await connection.close()


async def _cleanup(
    style_id: int | None,
    project_id: int | None,
    asset_id: int | None,
    file_paths: list[str],
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if asset_id is not None:
            await connection.execute(
                "DELETE FROM asset_images WHERE asset_id = $1", asset_id
            )
            await connection.execute("DELETE FROM assets WHERE id = $1", asset_id)
        if project_id is not None:
            await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        if style_id is not None:
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()
    for file_path in file_paths:
        (settings.DATA_DIR / file_path).unlink(missing_ok=True)


def test_asset_edit_and_current_image_preserve_downstream_rows() -> None:
    style_id = project_id = asset_id = None
    file_paths: list[str] = []
    try:
        with TestClient(app) as client:
            style_response = client.post(
                "/api/styles",
                json={
                    "name": "C003 Asset Test Style " + uuid4().hex,
                    "prompt_fragment": "asset test",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]

            project_response = client.post(
                "/api/projects",
                json={
                    "name": "C003 Asset Test Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            asset_response = client.post(
                f"/api/projects/{project_id}/assets",
                json={
                    "type": "character",
                    "name": "Asset Character",
                    "description": "Initial description",
                },
            )
            assert asset_response.status_code == 201
            asset = asset_response.json()
            asset_id = asset["id"]
            assert asset["revision"] == 1

            image = Image.new("RGB", (4, 4), (23, 81, 144))
            first_buffer = io.BytesIO()
            image.save(first_buffer, format="PNG")
            second_buffer = io.BytesIO()
            image.save(second_buffer, format="JPEG")

            first_upload = client.post(
                f"/api/assets/{asset_id}/images",
                files={
                    "file": (
                        "first-user-name.png",
                        first_buffer.getvalue(),
                        "image/png",
                    )
                },
            )
            second_upload = client.post(
                f"/api/assets/{asset_id}/images",
                files={
                    "file": (
                        "second-user-name.jpg",
                        second_buffer.getvalue(),
                        "image/jpeg",
                    )
                },
            )
            assert first_upload.status_code == 201
            assert second_upload.status_code == 201
            first_image = first_upload.json()
            second_image = second_upload.json()
            assert first_image["is_current"] is True
            assert second_image["is_current"] is False
            file_paths = asyncio.run(_asset_image_paths(asset_id))
            assert all((settings.DATA_DIR / path).is_file() for path in file_paths)

            description_change = client.patch(
                f"/api/assets/{asset_id}",
                json={"description": "Changed description"},
            )
            assert description_change.status_code == 200
            assert description_change.json()["revision"] == 3

            same_value = client.patch(
                f"/api/assets/{asset_id}",
                json={"name": "Asset Character", "description": "Changed description"},
            )
            assert same_value.status_code == 200
            assert same_value.json()["revision"] == 3
            assert same_value.json()["updated_at"] == description_change.json()["updated_at"]

            switched = client.put(
                f"/api/assets/{asset_id}/current-image",
                json={"image_id": second_image["id"]},
            )
            assert switched.status_code == 200
            assert switched.json()["id"] == second_image["id"]
            assert switched.json()["is_current"] is True
            assert client.get(f"/api/assets/{asset_id}").json()["revision"] == 4

            same_switch = client.put(
                f"/api/assets/{asset_id}/current-image",
                json={"image_id": second_image["id"]},
            )
            assert same_switch.status_code == 200
            assert same_switch.json()["is_current"] is True
            assert client.get(f"/api/assets/{asset_id}").json()["revision"] == 4
            assert all((settings.DATA_DIR / path).is_file() for path in file_paths)
    finally:
        asyncio.run(_cleanup(style_id, project_id, asset_id, file_paths))


def test_delete_asset_moves_all_images_to_trash() -> None:
    style_id = project_id = asset_id = None
    file_paths: list[str] = []
    try:
        with TestClient(app) as client:
            style_response = client.post(
                "/api/styles",
                json={
                    "name": "C003 Delete Test Style " + uuid4().hex,
                    "prompt_fragment": "asset delete test",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]

            project_response = client.post(
                "/api/projects",
                json={
                    "name": "C003 Delete Test Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            asset_response = client.post(
                f"/api/projects/{project_id}/assets",
                json={
                    "type": "scene",
                    "name": "Delete Scene",
                    "description": "Delete all versions",
                },
            )
            assert asset_response.status_code == 201
            asset_id = asset_response.json()["id"]

            image = Image.new("RGB", (4, 4), (144, 81, 23))
            png_buffer = io.BytesIO()
            image.save(png_buffer, format="PNG")
            jpeg_buffer = io.BytesIO()
            image.save(jpeg_buffer, format="JPEG")
            for filename, content, mime_type in (
                ("delete-first.png", png_buffer.getvalue(), "image/png"),
                ("delete-second.jpg", jpeg_buffer.getvalue(), "image/jpeg"),
            ):
                upload_response = client.post(
                    f"/api/assets/{asset_id}/images",
                    files={"file": (filename, content, mime_type)},
                )
                assert upload_response.status_code == 201

            file_paths = asyncio.run(_asset_image_paths(asset_id))
            formal_paths = [settings.DATA_DIR / path for path in file_paths]
            assert all(path.is_file() for path in formal_paths)

            delete_response = client.delete(f"/api/assets/{asset_id}")
            assert delete_response.status_code == 204
            assert client.get(f"/api/assets/{asset_id}").status_code == 404
            assert client.get(f"/api/assets/{asset_id}/images").status_code == 404
            assert asyncio.run(_asset_and_image_counts(asset_id)) == (0, 0)
            assert all(not path.exists() for path in formal_paths)
            trash_paths = [settings.DATA_DIR / "trash" / path for path in file_paths]
            assert all(path.is_file() for path in trash_paths)
    finally:
        asyncio.run(_cleanup(style_id, project_id, asset_id, []))
        for file_path in file_paths:
            (settings.DATA_DIR / file_path).unlink(missing_ok=True)
            (settings.DATA_DIR / "trash" / file_path).unlink(missing_ok=True)
