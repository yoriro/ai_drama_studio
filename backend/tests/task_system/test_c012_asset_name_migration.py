from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg


BACKEND = Path(__file__).resolve().parents[2]
PREVIOUS_HEAD = "6b8e3f0a1d24"
NEW_HEAD = "c012_asset_name_unique"


def _raw_database_url() -> str:
    return os.environ["DATABASE_URL"]


def _database_url(raw_url: str, database: str) -> str:
    parsed = urlsplit(raw_url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )


def _admin_url(raw_url: str) -> str:
    return _database_url(raw_url, "postgres")


def _run_alembic(database_url: str, command: str, revision: str):
    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = database_url
    child_env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=BACKEND,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _assert_alembic_success(result, label: str) -> None:
    assert result.returncode == 0, (
        f"{label}: rc={result.returncode}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )


async def _create_database(admin_url: str, database: str) -> None:
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: str, database: str) -> None:
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(f'DROP DATABASE "{database}"')
    finally:
        await connection.close()


async def _seed_old_schema(
    database_url: str,
    rows: list[tuple[int, str, str]],
) -> tuple[
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    dict[str, list[tuple[object, ...]]],
]:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            f"migration-style-{uuid4().hex}",
            "style",
        )
        project_ids: dict[int, int] = {}
        for project_number, _type, _name in rows:
            if project_number in project_ids:
                continue
            project_ids[project_number] = await connection.fetchval(
                "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
                f"migration-project-{project_number}-{uuid4().hex}",
                style_id,
            )
        for project_number, asset_type, name in rows:
            await connection.execute(
                "INSERT INTO assets "
                "(project_id, type, name, description, source, revision) "
                "VALUES ($1, $2, $3, $4, 'manual', 1)",
                project_ids[project_number],
                asset_type,
                name,
                f"description-{name}",
            )
        assets = await _read_assets(connection)
        first_asset = await connection.fetchrow(
            "SELECT id, project_id, type, name FROM assets ORDER BY id LIMIT 1"
        )
        if first_asset is None:
            raise AssertionError("migration fixture did not create an asset")
        episode_id = await connection.fetchval(
            "INSERT INTO episodes "
            "(project_id, seq, title, script_text, script_revision) "
            "VALUES ($1, 1, 'Migration episode', 'Migration script', 1) RETURNING id",
            first_asset["project_id"],
        )
        shot_id = await connection.fetchval(
            "INSERT INTO shots "
            "(episode_id, order_index, duration_est, shot_type, camera, "
            "description, dialogue, status, revision) "
            "VALUES ($1, 1, 5.0, 'wide', 'fixed', 'Migration shot', '', 'normal', 1) "
            "RETURNING id",
            episode_id,
        )
        clip_id = await connection.fetchval(
            "INSERT INTO clips "
            "(episode_id, requested_duration, generation_state, freshness, revision) "
            "VALUES ($1, 5, 'ready', 'fresh', 1) RETURNING id",
            episode_id,
        )
        await connection.execute(
            "INSERT INTO asset_images "
            "(asset_id, file_path, sha256, seed, source, is_current) "
            "VALUES ($1, 'assets/migration.png', 'migration-image', 1, 'uploaded', true)",
            first_asset["id"],
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            first_asset["id"],
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )
        await connection.execute(
            "INSERT INTO clip_ref_slots "
            "(clip_id, slot_no, asset_id, asset_name_snapshot, asset_type_snapshot, enabled) "
            "VALUES ($1, 1, $2, $3, $4, true)",
            clip_id,
            first_asset["id"],
            first_asset["name"],
            first_asset["type"],
        )
        await connection.execute(
            "INSERT INTO clip_videos "
            "(clip_id, file_path, sha256, seed, requested_duration, actual_duration, is_current) "
            "VALUES ($1, 'clips/migration.mp4', 'migration-video', 1, 5, 5.0, true)",
            clip_id,
        )
        templates = await connection.fetch(
            "SELECT key, content FROM prompt_templates ORDER BY key"
        )
        return assets, [tuple(row) for row in templates], await _read_dependencies(connection)
    finally:
        await connection.close()


async def _read_assets(connection: asyncpg.Connection) -> list[tuple[object, ...]]:
    rows = await connection.fetch(
        "SELECT id, project_id, type, name, description, source, revision "
        "FROM assets ORDER BY id"
    )
    return [tuple(row) for row in rows]


async def _read_dependencies(
    connection: asyncpg.Connection,
) -> dict[str, list[tuple[object, ...]]]:
    queries = {
        "episodes":
        "SELECT id, project_id, seq, title, script_text, script_revision, "
        "assets_generated_script_revision, shots_generated_script_revision "
        "FROM episodes ORDER BY id",
        "asset_images":
        "SELECT id, asset_id, file_path, sha256, seed, source, is_current, "
        "built_prompt, input_hash, input_snapshot, user_note "
        "FROM asset_images ORDER BY id",
        "shots":
        "SELECT id, episode_id, order_index, duration_est, shot_type, camera, "
        "description, dialogue, status, revision FROM shots ORDER BY id",
        "clips":
        "SELECT id, episode_id, generation_mode, user_note, requested_duration, "
        "prompt_cache, prompt_input_hash, generation_state, freshness, revision "
        "FROM clips ORDER BY id",
        "clip_ref_slots":
        "SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot, "
        "asset_type_snapshot, override_image_path, override_sha256, enabled "
        "FROM clip_ref_slots ORDER BY id",
        "clip_shots": "SELECT clip_id, shot_id, position FROM clip_shots ORDER BY clip_id, shot_id",
        "clip_videos":
        "SELECT id, clip_id, file_path, sha256, seed, requested_duration, "
        "actual_duration, is_current, built_prompt, input_hash, input_snapshot "
        "FROM clip_videos ORDER BY id",
        "shot_assets": "SELECT shot_id, asset_id FROM shot_assets ORDER BY shot_id, asset_id",
    }
    return {
        table: [tuple(row) for row in await connection.fetch(query)]
        for table, query in queries.items()
    }


async def _read_migration_state(
    database_url: str,
) -> tuple[
    str,
    bool,
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    dict[str, list[tuple[object, ...]]],
]:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        version = await connection.fetchval("SELECT version_num FROM alembic_version")
        constraint_exists = await connection.fetchval(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'assets'::regclass "
            "AND conname = 'uq_assets_project_name'"
            ")"
        )
        return (
            str(version),
            bool(constraint_exists),
            await _read_assets(connection),
            [
                tuple(row)
                for row in await connection.fetch(
                    "SELECT key, content FROM prompt_templates ORDER BY key"
                )
            ],
            await _read_dependencies(connection),
        )
    finally:
        await connection.close()


async def _assert_duplicate_is_rejected(database_url: str, project_id: int) -> None:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        try:
            await connection.execute(
                "INSERT INTO assets "
                "(project_id, type, name, description, source, revision) "
                "VALUES ($1, 'prop', 'Hero', 'duplicate', 'manual', 1)",
                project_id,
            )
        except asyncpg.exceptions.UniqueViolationError:
            return
        raise AssertionError("project-scoped asset name constraint accepted a duplicate")
    finally:
        await connection.close()


async def _run_migration_regression() -> None:
    raw_url = _raw_database_url()
    admin_url = _admin_url(raw_url).replace("+asyncpg", "", 1)

    empty_name = f"c012_migration_empty_{uuid4().hex}"
    empty_url = _database_url(raw_url, empty_name)
    await _create_database(admin_url, empty_name)
    try:
        result = _run_alembic(empty_url, "upgrade", NEW_HEAD)
        _assert_alembic_success(result, "empty upgrade")
        version, has_constraint, assets, templates, dependencies = await _read_migration_state(
            empty_url
        )
        assert version == NEW_HEAD
        assert has_constraint is True
        assert assets == []
        assert templates
        assert all(not rows for rows in dependencies.values())
    finally:
        await _drop_database(admin_url, empty_name)

    legal_name = f"c012_migration_legal_{uuid4().hex}"
    legal_url = _database_url(raw_url, legal_name)
    await _create_database(admin_url, legal_name)
    try:
        _assert_alembic_success(
            _run_alembic(legal_url, "upgrade", PREVIOUS_HEAD),
            "legal previous-head upgrade",
        )
        before_assets, before_templates, before_dependencies = await _seed_old_schema(
            legal_url,
            [(1, "character", "Hero"), (1, "scene", "Room"), (2, "character", "Hero")],
        )
        project_one_id = int(before_assets[0][1])

        _assert_alembic_success(
            _run_alembic(legal_url, "upgrade", NEW_HEAD),
            "legal upgrade",
        )
        after_upgrade = await _read_migration_state(legal_url)
        assert after_upgrade == (
            NEW_HEAD,
            True,
            before_assets,
            before_templates,
            before_dependencies,
        )
        await _assert_duplicate_is_rejected(legal_url, project_one_id)

        _assert_alembic_success(
            _run_alembic(legal_url, "downgrade", PREVIOUS_HEAD),
            "legal downgrade",
        )
        after_downgrade = await _read_migration_state(legal_url)
        assert after_downgrade == (
            PREVIOUS_HEAD,
            False,
            before_assets,
            before_templates,
            before_dependencies,
        )

        _assert_alembic_success(
            _run_alembic(legal_url, "upgrade", NEW_HEAD),
            "legal re-upgrade",
        )
        assert await _read_migration_state(legal_url) == (
            NEW_HEAD,
            True,
            before_assets,
            before_templates,
            before_dependencies,
        )
    finally:
        await _drop_database(admin_url, legal_name)

    invalid_cases = {
        "exact-collision": [(1, "character", "Hero"), (1, "scene", "Hero")],
        "normalized-collision": [(1, "character", "Hero"), (1, "scene", "  Hero  ")],
        "blank-name": [(1, "character", "   ")],
        "non-normalized": [(1, "character", " Hero ")],
    }
    for label, rows in invalid_cases.items():
        database = f"c012_migration_{label}_{uuid4().hex}"
        database_url = _database_url(raw_url, database)
        await _create_database(admin_url, database)
        try:
            _assert_alembic_success(
                _run_alembic(database_url, "upgrade", PREVIOUS_HEAD),
                f"{label} previous-head upgrade",
            )
            before_assets, before_templates, before_dependencies = await _seed_old_schema(
                database_url, rows
            )
            result = _run_alembic(database_url, "upgrade", NEW_HEAD)
            assert result.returncode != 0, f"{label} unexpectedly upgraded"
            output = result.stdout + result.stderr
            assert "assets name precheck failed" in output
            assert "project_id" in output
            assert "asset_id" in output
            assert "normalized" in output
            assert await _read_migration_state(database_url) == (
                PREVIOUS_HEAD,
                    False,
                    before_assets,
                    before_templates,
                    before_dependencies,
                )
        finally:
            await _drop_database(admin_url, database)


def test_c012_asset_name_migration_precheck_constraint_and_down_up() -> None:
    asyncio.run(_run_migration_regression())
