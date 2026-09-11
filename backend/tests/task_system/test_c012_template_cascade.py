from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.integrations.workflow_binding import (
    load_binding_snapshot,
    load_minimax_binding_snapshot,
)
from app.services.asset_image_inputs import build_asset_image_input_hash
from app.services.clip_video_inputs import build_clip_video_input_hash
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.services.generate_assets import enqueue_generate_assets
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.services.generate_shots import (
    enqueue_generate_shots,
    read_generate_shots_impact,
)
from app.services.prompt_templates import update_prompt_template
from app.services.styles import update_style
from app.schemas.prompt_templates import PromptTemplatePatch
from app.schemas.styles import StylePatch
from app.tasks import gen_asset_image as image_task
from app.tasks import gen_clip_video as video_task
from app.tasks.queue import ClaimedTask, TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture as cleanup_video_fixture,
    _create_fixture as create_video_fixture,
)
from tests.task_system.test_c007_gen_asset_image import (
    _FakeComfy as ImageComfy,
    _FakeVLLM as ImageVLLM,
)
from tests.task_system.test_c009_gen_clip_video import (
    _FakeComfy as VideoComfy,
    _FakeContext as VideoContext,
    _FakeVLLM as VideoVLLM,
)


SCRIPT2ASSETS_INITIAL = (
    "assets={{existing_assets}}|style={{style}}|script={{script}}"
)
SCRIPT2SHOTS_INITIAL = "assets={{assets}}|style={{style}}|script={{script}}"
ZIMAGE_INITIAL = "asset={{asset}}|style={{style}}|note={{user_note}}"
MINIMAX_INITIAL = (
    "shots={{shots}}|references={{references}}|style={{style}}|"
    "duration={{requested_duration}}|note={{user_note}}"
)

SCRIPT2ASSETS_CHANGED = (
    "changed-assets={{existing_assets}}|{{style}}|{{script}}"
)
SCRIPT2SHOTS_CHANGED = "changed-shots={{assets}}|{{style}}|{{script}}"
ZIMAGE_CHANGED = "changed-zimage={{asset}}|{{style}}|{{user_note}}"
MINIMAX_CHANGED = (
    "changed-minimax={{shots}}|{{references}}|{{style}}|"
    "{{requested_duration}}|{{user_note}}"
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _isolated_engine() -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _read_templates() -> dict[str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            "SELECT key, content FROM prompt_templates ORDER BY key"
        )
        return {str(row["key"]): str(row["content"]) for row in rows}
    finally:
        await connection.close()


async def _set_template(
    session_factory: async_sessionmaker[AsyncSession], key: str, content: str
) -> None:
    async with session_factory() as session:
        await update_prompt_template(
            session, key, PromptTemplatePatch(content=content)
        )


async def _set_style(
    session_factory: async_sessionmaker[AsyncSession], style_id: int, content: str
) -> None:
    async with session_factory() as session:
        await update_style(
            session, style_id, StylePatch(prompt_fragment=content)
        )


async def _install_test_templates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_template(session_factory, "script2assets", SCRIPT2ASSETS_INITIAL)
    await _set_template(session_factory, "script2shots", SCRIPT2SHOTS_INITIAL)
    await _set_template(session_factory, "zimage", ZIMAGE_INITIAL)
    await _set_template(session_factory, "minimaxh3", MINIMAX_INITIAL)


async def _read_payload(task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        raw = await connection.fetchval(
            "SELECT payload::text FROM tasks WHERE id = $1", task_id
        )
        assert isinstance(raw, str)
        payload = json.loads(raw)
        assert isinstance(payload, dict)
        return payload
    finally:
        await connection.close()


async def _delete_tasks(task_ids: list[int]) -> None:
    if not task_ids:
        return
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
        )
    finally:
        await connection.close()


async def _seed_clip_video(
    fixture: dict[str, object], data_dir: Path
) -> tuple[int, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        relative = Path(
            "projects",
            str(fixture["project_id"]),
            "episodes",
            str(fixture["episode_id"]),
            "clips",
            str(fixture["clip_id"]),
            "existing.mp4",
        )
        path = data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = b"c012 existing clip video"
        path.write_bytes(content)
        video_id = await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration,
                 actual_duration, is_current, built_prompt, input_hash,
                 input_snapshot)
            VALUES ($1, $2, $3, 1, 5, 5.0, false, 'old video prompt',
                    'old-video-hash', '{"source":"c012"}'::jsonb)
            RETURNING id
            """,
            fixture["clip_id"],
            relative.as_posix(),
            hashlib.sha256(content).hexdigest(),
        )
        assert video_id is not None
        return int(video_id), relative.as_posix()
    finally:
        await connection.close()


async def _delete_clip_video(video_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM clip_videos WHERE id = $1", video_id)
    finally:
        await connection.close()


async def _read_downstream(
    fixture: dict[str, object], data_dir: Path
) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        project_id = fixture["project_id"]
        episode_id = fixture["episode_id"]
        asset_ids = [fixture["character_id"], fixture["scene_id"]]
        shot_ids = fixture["shot_ids"]
        clip_id = fixture["clip_id"]
        assets = await connection.fetch(
            """
            SELECT id, project_id, type, name, description, source, revision,
                   image_prompt_cache, image_prompt_hash
            FROM assets WHERE project_id = $1 ORDER BY id
            """,
            project_id,
        )
        episodes = await connection.fetch(
            """
            SELECT id, project_id, seq, title, script_text, script_revision,
                   assets_generated_script_revision,
                   shots_generated_script_revision
            FROM episodes WHERE id = $1 ORDER BY id
            """,
            episode_id,
        )
        shots = await connection.fetch(
            """
            SELECT id, episode_id, order_index, duration_est, shot_type, camera,
                   description, dialogue, status, revision
            FROM shots WHERE id = ANY($1::int[]) ORDER BY id
            """,
            shot_ids,
        )
        shot_assets = await connection.fetch(
            """
            SELECT shot_id, asset_id FROM shot_assets
            WHERE shot_id = ANY($1::int[]) ORDER BY shot_id, asset_id
            """,
            shot_ids,
        )
        clips = await connection.fetch(
            """
            SELECT id, episode_id, user_note, requested_duration, prompt_cache,
                   prompt_input_hash, generation_state, freshness, revision
            FROM clips WHERE id = $1 ORDER BY id
            """,
            clip_id,
        )
        clip_shots = await connection.fetch(
            """
            SELECT clip_id, shot_id, position FROM clip_shots
            WHERE clip_id = $1 ORDER BY position
            """,
            clip_id,
        )
        slots = await connection.fetch(
            """
            SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot,
                   asset_type_snapshot, override_image_path, override_sha256,
                   enabled
            FROM clip_ref_slots WHERE clip_id = $1 ORDER BY slot_no
            """,
            clip_id,
        )
        images = await connection.fetch(
            """
            SELECT id, asset_id, file_path, sha256, seed, source, is_current,
                   built_prompt, input_hash, input_snapshot, user_note
            FROM asset_images WHERE asset_id = ANY($1::int[]) ORDER BY id
            """,
            asset_ids,
        )
        videos = await connection.fetch(
            """
            SELECT id, clip_id, file_path, sha256, seed, requested_duration,
                   actual_duration, is_current, built_prompt, input_hash,
                   input_snapshot
            FROM clip_videos WHERE clip_id = $1 ORDER BY id
            """,
            clip_id,
        )
        rows = {
            "assets": [dict(row) for row in assets],
            "episodes": [dict(row) for row in episodes],
            "shots": [dict(row) for row in shots],
            "shot_assets": [dict(row) for row in shot_assets],
            "clips": [dict(row) for row in clips],
            "clip_shots": [dict(row) for row in clip_shots],
            "slots": [dict(row) for row in slots],
            "images": [dict(row) for row in images],
            "videos": [dict(row) for row in videos],
        }
        media_paths = [
            str(row["file_path"])
            for row in [*images, *videos]
            if row["file_path"] != "pending"
        ]
        rows["files"] = {
            path: (data_dir / Path(path)).read_bytes() for path in media_paths
        }
        return rows
    finally:
        await connection.close()


async def _enqueue_image(
    session_factory: async_sessionmaker[AsyncSession], asset_id: int
) -> int:
    queue = TaskQueue(session_factory)
    async with session_factory() as session:
        result = await enqueue_generate_asset_image(
            session,
            queue,
            asset_id,
            user_note=None,
            request_id=None,
            workflow_binding=load_binding_snapshot(),
        )
    return int(result.task.id)


async def _enqueue_video(
    session_factory: async_sessionmaker[AsyncSession], clip_id: int
) -> int:
    queue = TaskQueue(session_factory)
    async with session_factory() as session:
        result = await enqueue_generate_clip_video(
            session,
            queue,
            clip_id,
            user_note=None,
            user_note_provided=False,
            request_id=None,
            workflow_binding=load_minimax_binding_snapshot(),
        )
    return int(result.task.id)


async def _enqueue_assets(
    session_factory: async_sessionmaker[AsyncSession], episode_id: int
) -> int:
    queue = TaskQueue(session_factory)
    async with session_factory() as session:
        result = await enqueue_generate_assets(session, queue, episode_id)
    return int(result.task.id)


async def _enqueue_shots(
    session_factory: async_sessionmaker[AsyncSession], episode_id: int
) -> int:
    queue = TaskQueue(session_factory)
    async with session_factory() as session:
        impact = await read_generate_shots_impact(session, episode_id)
    async with session_factory() as session:
        result = await enqueue_generate_shots(
            session, queue, episode_id, impact.confirm_token
        )
    return int(result.task.id)


def _expected_image_hash(payload: dict[str, object]) -> str:
    snapshot = payload["input_snapshot"]
    assert isinstance(snapshot, dict)
    asset = snapshot["asset"]
    workflow = snapshot["workflow"]
    assert isinstance(asset, dict) and isinstance(workflow, dict)
    return build_asset_image_input_hash(
        asset_name=asset["name"],
        asset_description=asset["description"],
        asset_revision=asset["revision"],
        style_prompt_fragment=snapshot["style"],
        template_content=snapshot["template_content"],
        user_note=snapshot["user_note"],
        model=snapshot["model"],
        workflow_hash=workflow["hash"],
    )


def _expected_video_hash(payload: dict[str, object]) -> str:
    snapshot = payload["input_snapshot"]
    assert isinstance(snapshot, dict)
    workflow = snapshot["workflow"]
    assert isinstance(workflow, dict)
    return build_clip_video_input_hash(
        shots=snapshot["shots"],
        references=snapshot["references"],
        style_prompt_fragment=snapshot["style"],
        template_content=snapshot["template_content"],
        user_note=snapshot["user_note"],
        requested_duration=snapshot["requested_duration"],
        model=snapshot["model"],
        workflow_hash=workflow["hash"],
    )


class _PromptContext:
    def __init__(self) -> None:
        self.queue = SimpleNamespace()

    async def cancel_safe_point(self) -> SimpleNamespace:
        return SimpleNamespace(task=SimpleNamespace(status="running"))

    async def heartbeat(self, _progress: float) -> None:
        return None


async def _run_image_prompt_only(
    payload: dict[str, object],
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    vllm: ImageVLLM,
    comfy: ImageComfy,
) -> None:
    task = ClaimedTask(
        id=700001,
        type="gen_asset_image",
        target_id=1,
        request_id=None,
        payload=copy.deepcopy(payload),
    )
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(image_task, "VLLMClient", lambda _url: vllm)
    monkeypatch.setattr(image_task, "ComfyClient", lambda _url: comfy)

    async def no_commit(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(image_task, "commit_generated_asset_image", no_commit)
    await image_task.gen_asset_image_handler(task, _PromptContext())


async def _run_video_prompt_only(
    payload: dict[str, object],
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    vllm: VideoVLLM,
    comfy: VideoComfy,
) -> None:
    task = ClaimedTask(
        id=700002,
        type="gen_clip_video",
        target_id=1,
        request_id=None,
        payload=copy.deepcopy(payload),
    )
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(video_task, "VLLMClient", lambda _url: vllm)
    monkeypatch.setattr(video_task, "ComfyClient", lambda _url: comfy)
    result = await video_task.gen_clip_video_handler(task, VideoContext())
    if result is not None:
        result.temp_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("mutation", "expected_image_change", "expected_video_change"),
    [
        ("style", True, True),
        ("zimage", True, False),
        ("minimaxh3", False, True),
    ],
    ids=["style-affects-both", "zimage-affects-image", "minimax-affects-video"],
)
def test_c012_template_changes_rebuild_exact_r4_cache_once(
    mutation: str,
    expected_image_change: bool,
    expected_video_change: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        original_templates = await _read_templates()
        fixture = await create_video_fixture(tmp_path)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        isolated_engine, session_factory = _isolated_engine()
        task_ids: list[int] = []
        try:
            await _install_test_templates(session_factory)
            await _set_style(session_factory, fixture["style_id"], "原始风格")

            seed_image_id = await _enqueue_image(
                session_factory, fixture["character_id"]
            )
            seed_image = await _read_payload(seed_image_id)
            seed_video_id = await _enqueue_video(session_factory, fixture["clip_id"])
            seed_video = await _read_payload(seed_video_id)
            task_ids.extend([seed_image_id, seed_video_id])
            assert seed_image["input_hash"] == _expected_image_hash(seed_image)
            assert seed_video["input_hash"] == _expected_video_hash(seed_video)

            connection = await asyncpg.connect(_database_url())
            try:
                await connection.execute(
                    "UPDATE assets SET image_prompt_cache = $1, image_prompt_hash = $2 WHERE id = $3",
                    "cached image prompt",
                    seed_image["input_hash"],
                    fixture["character_id"],
                )
                await connection.execute(
                    "UPDATE clips SET prompt_cache = $1, prompt_input_hash = $2 WHERE id = $3",
                    "cached video prompt",
                    seed_video["input_hash"],
                    fixture["clip_id"],
                )
                await connection.execute(
                    "DELETE FROM tasks WHERE id = ANY($1::int[])",
                    [seed_image_id, seed_video_id],
                )
            finally:
                await connection.close()
            task_ids.clear()

            hit_image_id = await _enqueue_image(
                session_factory, fixture["character_id"]
            )
            hit_video_id = await _enqueue_video(session_factory, fixture["clip_id"])
            task_ids.extend([hit_image_id, hit_video_id])
            hit_image = await _read_payload(hit_image_id)
            hit_video = await _read_payload(hit_video_id)
            assert hit_image["input_hash"] == seed_image["input_hash"]
            assert hit_video["input_hash"] == seed_video["input_hash"]
            assert hit_image["input_snapshot"]["cached_prompt"] == "cached image prompt"
            assert hit_video["input_snapshot"]["cached_prompt"] == "cached video prompt"

            if mutation == "style":
                await _set_style(session_factory, fixture["style_id"], "变更风格")
            elif mutation == "zimage":
                await _set_template(session_factory, "zimage", ZIMAGE_CHANGED)
            else:
                await _set_template(session_factory, "minimaxh3", MINIMAX_CHANGED)

            changed_image_id = await _enqueue_image(
                session_factory, fixture["character_id"]
            )
            changed_video_id = await _enqueue_video(
                session_factory, fixture["clip_id"]
            )
            task_ids.extend([changed_image_id, changed_video_id])
            changed_image = await _read_payload(changed_image_id)
            changed_video = await _read_payload(changed_video_id)

            assert changed_image["input_hash"] == _expected_image_hash(changed_image)
            assert changed_video["input_hash"] == _expected_video_hash(changed_video)
            assert changed_image["input_hash"] != seed_image["input_hash"] if expected_image_change else changed_image["input_hash"] == seed_image["input_hash"]
            assert changed_video["input_hash"] != seed_video["input_hash"] if expected_video_change else changed_video["input_hash"] == seed_video["input_hash"]
            assert (
                changed_image["input_snapshot"]["cached_prompt"] is None
                if expected_image_change
                else changed_image["input_snapshot"]["cached_prompt"] == "cached image prompt"
            )
            assert (
                changed_video["input_snapshot"]["cached_prompt"] is None
                if expected_video_change
                else changed_video["input_snapshot"]["cached_prompt"] == "cached video prompt"
            )
            if mutation == "style":
                assert changed_image["input_snapshot"]["style"] == "变更风格"
                assert changed_video["input_snapshot"]["style"] == "变更风格"
            elif mutation == "zimage":
                assert changed_image["input_snapshot"]["template_content"] == ZIMAGE_CHANGED
                assert changed_video["input_snapshot"]["template_content"] == MINIMAX_INITIAL
            else:
                assert changed_image["input_snapshot"]["template_content"] == ZIMAGE_INITIAL
                assert changed_video["input_snapshot"]["template_content"] == MINIMAX_CHANGED

            image_vllm = ImageVLLM([], "success")
            video_vllm = VideoVLLM([])
            await _run_image_prompt_only(
                hit_image,
                tmp_path / "hit-image",
                monkeypatch,
                image_vllm,
                ImageComfy([], hit_image["input_snapshot"]["comfy_prompt_id"], "success"),
            )
            await _run_image_prompt_only(
                changed_image,
                tmp_path / "changed-image",
                monkeypatch,
                image_vllm,
                ImageComfy([], changed_image["input_snapshot"]["comfy_prompt_id"], "success"),
            )
            await _run_video_prompt_only(
                hit_video,
                tmp_path,
                monkeypatch,
                video_vllm,
                VideoComfy([]),
            )
            await _run_video_prompt_only(
                changed_video,
                tmp_path,
                monkeypatch,
                video_vllm,
                VideoComfy([]),
            )
            assert len(image_vllm.chat_requests) == int(expected_image_change)
            assert len(video_vllm.chat_requests) == int(expected_video_change)
            assert image_vllm.chat_requests == (
                [
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": changed_image["input_snapshot"]["rendered_prompt"],
                            }
                        ],
                        "model": changed_image["input_snapshot"]["model"],
                        "temperature": changed_image["input_snapshot"]["temperature"],
                        "schema_name": "zimage",
                        "schema": changed_image["input_snapshot"]["guided_json_schema"]["json_schema"]["schema"],
                    }
                ]
                if expected_image_change
                else []
            )
        finally:
            await _delete_tasks(task_ids)
            await cleanup_video_fixture(fixture)
            for key, content in original_templates.items():
                await _set_template(session_factory, key, content)
            await isolated_engine.dispose()

    asyncio.run(run())


def test_c012_template_edits_freeze_all_inflight_payloads_and_do_not_retrofit_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        original_templates = await _read_templates()
        fixture = await create_video_fixture(tmp_path)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        video_id, video_path = await _seed_clip_video(fixture, tmp_path)
        isolated_engine, session_factory = _isolated_engine()
        task_ids: list[int] = []
        try:
            await _install_test_templates(session_factory)
            await _set_style(session_factory, fixture["style_id"], "冻结前风格")

            assets_task_id = await _enqueue_assets(
                session_factory, fixture["episode_id"]
            )
            task_ids.append(assets_task_id)
            shots_task_id = await _enqueue_shots(
                session_factory, fixture["episode_id"]
            )
            task_ids.append(shots_task_id)
            image_task_id = await _enqueue_image(
                session_factory, fixture["character_id"]
            )
            task_ids.append(image_task_id)
            video_task_id = await _enqueue_video(
                session_factory, fixture["clip_id"]
            )
            task_ids.append(video_task_id)
            before_payloads = {
                task_id: await _read_payload(task_id) for task_id in task_ids
            }
            before_downstream = await _read_downstream(fixture, tmp_path)
            assert [
                before_payloads[task_ids[index]]["input_hash"] for index in range(4)
            ] == [
                None,
                None,
                before_payloads[image_task_id]["input_hash"],
                before_payloads[video_task_id]["input_hash"],
            ]

            await _set_style(session_factory, fixture["style_id"], "冻结后风格")
            await _set_template(session_factory, "script2assets", SCRIPT2ASSETS_CHANGED)
            await _set_template(session_factory, "script2shots", SCRIPT2SHOTS_CHANGED)
            await _set_template(session_factory, "zimage", ZIMAGE_CHANGED)
            await _set_template(session_factory, "minimaxh3", MINIMAX_CHANGED)

            after_payloads = {
                task_id: await _read_payload(task_id) for task_id in task_ids
            }
            assert after_payloads == before_payloads
            assert await _read_downstream(fixture, tmp_path) == before_downstream
            assert (tmp_path / Path(video_path)).read_bytes() == b"c012 existing clip video"

            before_image_hash = before_payloads[image_task_id]["input_hash"]
            before_video_hash = before_payloads[video_task_id]["input_hash"]
            await _delete_tasks(task_ids)
            task_ids.clear()
            new_assets_id = await _enqueue_assets(
                session_factory, fixture["episode_id"]
            )
            new_shots_id = await _enqueue_shots(
                session_factory, fixture["episode_id"]
            )
            new_image_id = await _enqueue_image(
                session_factory, fixture["character_id"]
            )
            new_video_id = await _enqueue_video(session_factory, fixture["clip_id"])
            task_ids.extend([new_assets_id, new_shots_id, new_image_id, new_video_id])
            new_payloads = {
                task_id: await _read_payload(task_id) for task_id in task_ids
            }

            assert new_payloads[new_assets_id]["input_hash"] is None
            assert new_payloads[new_assets_id]["input_snapshot"]["template_content"] == SCRIPT2ASSETS_CHANGED
            assert new_payloads[new_assets_id]["input_snapshot"]["style"] == "冻结后风格"
            assert new_payloads[new_shots_id]["input_hash"] is None
            assert new_payloads[new_shots_id]["input_snapshot"]["template_content"] == SCRIPT2SHOTS_CHANGED
            assert new_payloads[new_shots_id]["input_snapshot"]["style"] == "冻结后风格"
            assert new_payloads[new_image_id]["input_hash"] == _expected_image_hash(new_payloads[new_image_id])
            assert new_payloads[new_image_id]["input_hash"] != before_image_hash
            assert new_payloads[new_image_id]["input_snapshot"]["cached_prompt"] is None
            assert new_payloads[new_image_id]["input_snapshot"]["template_content"] == ZIMAGE_CHANGED
            assert new_payloads[new_video_id]["input_hash"] == _expected_video_hash(new_payloads[new_video_id])
            assert new_payloads[new_video_id]["input_hash"] != before_video_hash
            assert new_payloads[new_video_id]["input_snapshot"]["cached_prompt"] is None
            assert new_payloads[new_video_id]["input_snapshot"]["template_content"] == MINIMAX_CHANGED
            assert await _read_downstream(fixture, tmp_path) == before_downstream
        finally:
            await _delete_tasks(task_ids)
            await _delete_clip_video(video_id)
            await cleanup_video_fixture(fixture)
            for key, content in original_templates.items():
                await _set_template(session_factory, key, content)
            await isolated_engine.dispose()

    asyncio.run(run())
