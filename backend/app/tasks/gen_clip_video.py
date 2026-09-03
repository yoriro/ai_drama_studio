from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.db.session import async_session_factory
from app.integrations.comfy import (
    ComfyClient,
    parse_comfy_upload_response,
    parse_comfy_video_history,
)
from app.services.asset_files import resolve_data_path
from app.services.clip_video_inputs import (
    build_minimaxh3_response_format,
    inject_minimaxh3_workflow_inputs,
    validate_minimaxh3_response,
)
from app.services.video_files import cleanup_clip_video_temp, write_clip_video
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


logger = logging.getLogger("app.tasks.gen_clip_video")

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SEED_MAX = (1 << 63) - 1


class ComfyResourceError(RuntimeError):
    """The Comfy operation and one or more cleanup operations failed."""


@dataclass(frozen=True, slots=True)
class GeneratedClipVideo:
    temp_path: Path
    built_prompt: str


def _snapshot(task: ClaimedTask) -> dict[str, Any]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_clip_video input_snapshot must be an object")
    return snapshot


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gen_clip_video {field} must be non-blank text")
    return value


def _temperature(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("gen_clip_video temperature must be a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("gen_clip_video temperature must be finite")
    return numeric


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("gen_clip_video seed must be a 63-bit integer")
    if not 0 <= value <= _SEED_MAX:
        raise ValueError("gen_clip_video seed must be a 63-bit integer")
    return value


def _duration(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            "gen_clip_video requested_duration must be a positive integer"
        )
    return value


def _guided_schema(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    guided = snapshot.get("guided_json_schema")
    if guided != build_minimaxh3_response_format():
        raise ValueError("gen_clip_video guided_json_schema is not minimaxh3")
    schema = guided["json_schema"]["schema"]
    if not isinstance(schema, Mapping):
        raise ValueError(
            "gen_clip_video guided_json_schema schema must be an object"
        )
    return schema


def _response_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("vLLM response must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ValueError("vLLM choice must be an object")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("vLLM choice message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("vLLM response content must be a non-empty string")
    return content


def _built_prompt(response: Mapping[str, Any]) -> str:
    content = _response_content(response)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("vLLM response is not valid minimaxh3 JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("minimaxh3 response must be an object")
    return validate_minimaxh3_response(parsed)


def _workflow(
    snapshot: Mapping[str, Any],
) -> tuple[
    Mapping[str, Any],
    str,
    str,
    str,
    Sequence[object],
    Sequence[object],
    str,
]:
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, Mapping):
        raise ValueError("gen_clip_video workflow must be an object")
    if workflow.get("name") != "minimaxh3":
        raise ValueError("gen_clip_video workflow name must be minimaxh3")
    _required_text(workflow.get("hash"), "workflow.hash")
    prompt_path = _required_text(
        workflow.get("prompt_path"), "workflow.prompt_path"
    )
    seed_path = _required_text(workflow.get("seed_path"), "workflow.seed_path")
    duration_path = _required_text(
        workflow.get("duration_path"), "workflow.duration_path"
    )
    ref_image_paths = workflow.get("ref_image_paths")
    ref_consumer_paths = workflow.get("ref_consumer_paths")
    if not isinstance(ref_image_paths, Sequence) or isinstance(
        ref_image_paths, (str, bytes, bytearray)
    ):
        raise ValueError("gen_clip_video workflow.ref_image_paths must be an array")
    if not isinstance(ref_consumer_paths, Sequence) or isinstance(
        ref_consumer_paths, (str, bytes, bytearray)
    ):
        raise ValueError(
            "gen_clip_video workflow.ref_consumer_paths must be an array"
        )
    if workflow.get("optional_refs") is not False:
        raise ValueError("gen_clip_video workflow.optional_refs must be false")
    output_node = _required_text(
        workflow.get("output_node"), "workflow.output_node"
    )
    if output_node != "168":
        raise ValueError("gen_clip_video workflow.output_node must be 168")
    definition = workflow.get("definition")
    if not isinstance(definition, Mapping):
        raise ValueError("gen_clip_video workflow definition must be an object")
    return (
        definition,
        prompt_path,
        seed_path,
        duration_path,
        ref_image_paths,
        ref_consumer_paths,
        output_node,
    )


def _reference_media(
    snapshot: Mapping[str, Any],
) -> tuple[Sequence[Mapping[str, Any]], list[tuple[str, str, bytes]]]:
    references = snapshot.get("references")
    media = snapshot.get("reference_media")
    if not isinstance(references, Sequence) or isinstance(
        references, (str, bytes, bytearray)
    ):
        raise ValueError("gen_clip_video references must be an array")
    if not isinstance(media, Sequence) or isinstance(media, (str, bytes, bytearray)):
        raise ValueError("gen_clip_video reference_media must be an array")
    if not 1 <= len(references) <= 9 or len(media) != len(references):
        raise ValueError("gen_clip_video references must contain 1 to 9 items")

    validated_references: list[Mapping[str, Any]] = []
    uploads: list[tuple[str, str, bytes]] = []
    for index, (reference_value, media_value) in enumerate(
        zip(references, media, strict=True), start=1
    ):
        if not isinstance(reference_value, Mapping):
            raise ValueError(
                f"gen_clip_video references[{index - 1}] must be an object"
            )
        reference_name = reference_value.get("reference_name")
        if reference_name != f"subject{index}":
            raise ValueError(
                f"gen_clip_video references[{index - 1}].reference_name is invalid"
            )
        if not isinstance(media_value, Mapping):
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}] must be an object"
            )
        file_path = media_value.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}].file_path is invalid"
            )
        if "\x00" in file_path or "\\" in file_path:
            raise ValueError("gen_clip_video reference media path is not safe")
        parsed_path = PurePosixPath(file_path)
        if parsed_path.is_absolute() or any(
            part in {"", ".", ".."} for part in parsed_path.parts
        ):
            raise ValueError("gen_clip_video reference media path is not safe")
        extension = media_value.get("extension")
        if not isinstance(extension, str) or extension.lower() not in _IMAGE_EXTENSIONS:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}].extension is invalid"
            )
        normalized_extension = extension.lower()
        suffix = parsed_path.suffix.removeprefix(".").lower()
        if suffix != normalized_extension:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}] extension does not match path"
            )
        digest = media_value.get("sha256")
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}].sha256 is invalid"
            )
        resolved_path = resolve_data_path(settings.DATA_DIR, file_path)
        try:
            content = resolved_path.read_bytes()
        except OSError as exc:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}] is unavailable"
            ) from exc
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != digest:
            raise ValueError(
                f"gen_clip_video reference_media[{index - 1}] hash does not match"
            )
        validated_references.append(reference_value)
        uploads.append(
            (f"subject{index}.{normalized_extension}", normalized_extension, content)
        )
    return validated_references, uploads


def _canceled(change: object) -> bool:
    task = getattr(change, "task", None)
    return getattr(task, "status", None) == "canceled"


async def _cancel_safe_point(context: WorkerContext) -> bool:
    return _canceled(await context.cancel_safe_point())


async def _consume_websocket(
    websocket: Any,
    *,
    prompt_id: str,
    context: WorkerContext,
) -> bool:
    progress = 0.0
    while True:
        if await _cancel_safe_point(context):
            return True
        try:
            raw_message = await websocket.recv()
        except ConnectionClosed as exc:
            raise RuntimeError(
                "Comfy websocket closed before a terminal message"
            ) from exc
        if isinstance(raw_message, bytes):
            continue
        if not isinstance(raw_message, str):
            raise TypeError("Comfy websocket message must be text or binary")
        message = json.loads(raw_message)
        if not isinstance(message, Mapping):
            raise ValueError("Comfy websocket message must be a JSON object")
        message_type = message.get("type")
        if not isinstance(message_type, str):
            raise ValueError("Comfy websocket message type must be text")
        if message_type not in {
            "progress",
            "executing",
            "execution_success",
            "execution_error",
            "execution_interrupted",
        }:
            continue
        data = message.get("data")
        if not isinstance(data, Mapping):
            raise ValueError(f"Comfy {message_type} data must be an object")
        related_prompt_id = data.get("prompt_id")
        if not isinstance(related_prompt_id, str):
            raise ValueError(f"Comfy {message_type} prompt_id must be text")
        if related_prompt_id != prompt_id:
            continue

        if message_type == "progress":
            value = data.get("value")
            maximum = data.get("max")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or isinstance(maximum, bool)
                or not isinstance(maximum, (int, float))
                or not math.isfinite(float(maximum))
                or maximum <= 0
                or value < 0
                or value > maximum
            ):
                raise ValueError("Comfy progress value/max is invalid")
            mapped = 0.25 + 0.65 * (float(value) / float(maximum))
            if mapped > progress:
                progress = mapped
                await context.heartbeat(progress)
            continue

        if message_type == "executing":
            if progress < 0.25:
                progress = 0.25
                await context.heartbeat(progress)
            continue

        if message_type == "execution_success":
            return False

        if message_type == "execution_interrupted":
            if not await context.cancel_requested():
                raise RuntimeError(
                    "Comfy execution_interrupted without cancellation intent"
                )
            return True

        node = _required_text(data.get("node"), "Comfy execution_error.node")
        node_type = _required_text(
            data.get("node_type"), "Comfy execution_error.node_type"
        )
        exception_message = _required_text(
            data.get("exception_message"),
            "Comfy execution_error.exception_message",
        )
        raise RuntimeError(
            "Comfy execution_error "
            f"node={node} type={node_type} exception={exception_message}"
        )


def _raise_comfy_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_error: BaseException | None,
    free_error: BaseException | None,
) -> None:
    errors = [
        ("Comfy primary error", primary_error),
        ("Comfy temporary cleanup error", cleanup_error),
        ("Comfy free error", free_error),
    ]
    present = [(label, error) for label, error in errors if error is not None]
    if not present:
        return
    if len(present) == 1 and present[0][0] == "Comfy primary error":
        return
    message = "; ".join(f"{label}: {error}" for label, error in present)
    cause = primary_error or cleanup_error or free_error
    raise ComfyResourceError(message) from cause


async def _run_comfy(
    comfy: ComfyClient,
    *,
    task_id: int,
    workflow: Mapping[str, Any],
    prompt_path: str,
    seed_path: str,
    duration_path: str,
    ref_image_paths: Sequence[object],
    ref_consumer_paths: Sequence[object],
    output_node: str,
    references: Sequence[Mapping[str, Any]],
    uploads: Sequence[tuple[str, str, bytes]],
    built_prompt: str,
    seed: int,
    requested_duration: int,
    prompt_id: str,
    context: WorkerContext,
) -> Path | None:
    del references
    temp_path: Path | None = None
    cleanup_error: BaseException | None = None
    try:
        upload_paths: list[str] = []
        subfolder = f"c009/task-{task_id}"
        for index, (filename, extension, content) in enumerate(uploads, start=1):
            del extension
            if await _cancel_safe_point(context):
                return None
            upload_response = await comfy.upload_image(
                filename=filename,
                content=content,
                subfolder=subfolder,
            )
            parsed_upload = parse_comfy_upload_response(
                upload_response,
                expected_extension=filename.rsplit(".", 1)[-1],
            )
            upload_paths.append(parsed_upload.path)
            if await _cancel_safe_point(context):
                return None
            logger.debug(
                "Uploaded gen_clip_video reference task_id=%s reference=%s path=%s",
                task_id,
                index,
                parsed_upload.path,
            )

        injected_workflow = inject_minimaxh3_workflow_inputs(
            workflow,
            prompt_path=prompt_path,
            seed_path=seed_path,
            duration_path=duration_path,
            ref_image_paths=ref_image_paths,
            ref_consumer_paths=ref_consumer_paths,
            built_prompt=built_prompt,
            seed=seed,
            requested_duration=requested_duration,
            upload_paths=upload_paths,
        )
        if await _cancel_safe_point(context):
            return None

        async with comfy.connect_ws(prompt_id) as websocket:
            submit_response = await comfy.submit(
                prompt=injected_workflow,
                client_id=prompt_id,
                prompt_id=prompt_id,
            )
            if not isinstance(submit_response, Mapping):
                raise ValueError("Comfy submit response must be an object")
            if submit_response.get("prompt_id") != prompt_id:
                raise ValueError(
                    "Comfy submit returned a prompt id different from the request"
                )
            interrupted = await _consume_websocket(
                websocket,
                prompt_id=prompt_id,
                context=context,
            )
            if interrupted:
                return None
            if await _cancel_safe_point(context):
                return None
            history = await comfy.history(prompt_id)
            video = parse_comfy_video_history(
                history,
                prompt_id=prompt_id,
                output_node=output_node,
            )
            if await _cancel_safe_point(context):
                return None
            temp_path = await write_clip_video(
                comfy.view_stream(
                    filename=video.filename,
                    subfolder=video.subfolder,
                    media_type=video.type,
                ),
                data_dir=settings.DATA_DIR,
                task_id=task_id,
            )
            if await _cancel_safe_point(context):
                cleanup_clip_video_temp(temp_path)
                temp_path = None
                return None
        return temp_path
    finally:
        primary_error = sys.exc_info()[1]
        if (
            primary_error is not None
            and temp_path is not None
        ):
            try:
                cleanup_clip_video_temp(temp_path)
                temp_path = None
            except OSError as exc:
                cleanup_error = exc
        _raise_comfy_cleanup_errors(primary_error, cleanup_error, None)


async def gen_clip_video_handler(
    task: ClaimedTask, context: WorkerContext
) -> GeneratedClipVideo | None:
    snapshot = _snapshot(task)
    input_hash = _required_text(task.payload.get("input_hash"), "input_hash")
    _guided_schema(snapshot)
    cached_prompt = snapshot.get("cached_prompt")
    if cached_prompt is not None and not isinstance(cached_prompt, str):
        raise ValueError("gen_clip_video cached_prompt must be text or null")

    comfy = ComfyClient(str(settings.COMFY_BASE_URL))
    temp_path: Path | None = None
    cleanup_error: BaseException | None = None
    free_error: BaseException | None = None
    vllm: VLLMClient | None = None
    wake_succeeded = False
    sleep_attempted = False
    try:
        try:
            if await _cancel_safe_point(context):
                return None

            vllm = VLLMClient(str(settings.VLLM_BASE_URL))
            if cached_prompt is None:
                rendered_prompt = _required_text(
                    snapshot.get("rendered_prompt"), "rendered_prompt"
                )
                model = _required_text(snapshot.get("model"), "model")
                temperature = _temperature(snapshot.get("temperature"))
                schema = _guided_schema(snapshot)
                await vllm.wake()
                wake_succeeded = True
                response = await vllm.structured_chat(
                    messages=[{"role": "user", "content": rendered_prompt}],
                    model=model,
                    temperature=temperature,
                    schema_name="minimaxh3",
                    schema=schema,
                )
                if not isinstance(response, Mapping):
                    raise ValueError("vLLM response must be an object")
                built_prompt = _built_prompt(response)
                cache_state = "miss"
            else:
                built_prompt = _required_text(cached_prompt, "cached_prompt")
                cache_state = "hit"

            logger.info(
                "gen_clip_video prompt built task_id=%s cache=%s input_hash=%s built_prompt=%s",
                task.id,
                cache_state,
                input_hash,
                built_prompt,
                extra={
                    "task_id": task.id,
                    "input_hash": input_hash,
                    "built_prompt": built_prompt,
                },
            )

            if await _cancel_safe_point(context):
                return None
            sleep_attempted = True
            await vllm.sleep()
            wake_succeeded = False

            if await _cancel_safe_point(context):
                return None
            (
                workflow,
                prompt_path,
                seed_path,
                duration_path,
                ref_image_paths,
                ref_consumer_paths,
                output_node,
            ) = _workflow(snapshot)
            seed = _seed(snapshot.get("seed"))
            requested_duration = _duration(snapshot.get("requested_duration"))
            prompt_id = _required_text(
                snapshot.get("comfy_prompt_id"), "comfy_prompt_id"
            )
            references, uploads = _reference_media(snapshot)
            temp_path = await _run_comfy(
                comfy,
                task_id=task.id,
                workflow=workflow,
                prompt_path=prompt_path,
                seed_path=seed_path,
                duration_path=duration_path,
                ref_image_paths=ref_image_paths,
                ref_consumer_paths=ref_consumer_paths,
                output_node=output_node,
                references=references,
                uploads=uploads,
                built_prompt=built_prompt,
                seed=seed,
                requested_duration=requested_duration,
                prompt_id=prompt_id,
                context=context,
            )
            if temp_path is None:
                return None
            if await _cancel_safe_point(context):
                cleanup_clip_video_temp(temp_path)
                temp_path = None
                return None
            return GeneratedClipVideo(temp_path=temp_path, built_prompt=built_prompt)
        finally:
            if vllm is not None and wake_succeeded and not sleep_attempted:
                await vllm.sleep()
    finally:
        primary_error = sys.exc_info()[1]
        try:
            await comfy.free()
        except (
            httpx.HTTPError,
            OSError,
            TimeoutError,
            RuntimeError,
            ValueError,
        ) as exc:
            free_error = exc
        if (
            (primary_error is not None or free_error is not None)
            and temp_path is not None
        ):
            try:
                cleanup_clip_video_temp(temp_path)
                temp_path = None
            except OSError as exc:
                cleanup_error = exc
        _raise_comfy_cleanup_errors(primary_error, cleanup_error, free_error)


async def gen_clip_video_task_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    generated = await gen_clip_video_handler(task, context)
    if generated is None:
        return
    from app.services.clip_video_commit import commit_generated_clip_video

    async with async_session_factory() as session:
        completed = await commit_generated_clip_video(
            session,
            context.queue,
            task,
            generated,
            data_dir=settings.DATA_DIR,
        )
    if completed is not None:
        await context.queue.publish_committed(completed)
