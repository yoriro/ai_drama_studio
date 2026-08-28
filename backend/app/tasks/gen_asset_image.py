from __future__ import annotations

import json
import logging
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.db.session import async_session_factory
from app.integrations.comfy import ComfyClient
from app.services.asset_image_commit import (
    GeneratedPng,
    cleanup_generated_png,
    commit_generated_asset_image,
    write_generated_png,
)
from app.services.asset_image_inputs import (
    inject_zimage_workflow_inputs,
    validate_zimage_response,
)
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


logger = logging.getLogger("app.tasks.gen_asset_image")


class ComfyResourceError(RuntimeError):
    """The Comfy operation and its required free operation both failed."""


def _snapshot(task: ClaimedTask) -> dict[str, Any]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_asset_image input_snapshot must be an object")
    return snapshot


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gen_asset_image {field} must be non-blank text")
    return value


def _temperature(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("gen_asset_image temperature must be a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("gen_asset_image temperature must be finite")
    return numeric


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**63:
        raise ValueError("gen_asset_image seed must be a 63-bit integer")
    return value


def _guided_schema(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    guided = snapshot.get("guided_json_schema")
    if not isinstance(guided, Mapping) or set(guided) != {
        "type",
        "json_schema",
    }:
        raise ValueError(
            "gen_asset_image guided_json_schema must be a response_format object"
        )
    if guided.get("type") != "json_schema":
        raise ValueError(
            "gen_asset_image guided_json_schema type must be json_schema"
        )
    json_schema = guided.get("json_schema")
    if not isinstance(json_schema, Mapping) or set(json_schema) != {
        "name",
        "strict",
        "schema",
    }:
        raise ValueError(
            "gen_asset_image guided_json_schema json_schema is invalid"
        )
    if json_schema.get("name") != "zimage":
        raise ValueError(
            "gen_asset_image guided_json_schema name must be zimage"
        )
    if json_schema.get("strict") is not True:
        raise ValueError("gen_asset_image guided_json_schema must be strict")
    schema = json_schema.get("schema")
    if not isinstance(schema, Mapping):
        raise ValueError("gen_asset_image guided_json_schema schema must be an object")
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
        raise ValueError("vLLM response is not valid zimage JSON") from exc
    return validate_zimage_response(parsed)


def _workflow(snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, str, str]:
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, Mapping):
        raise ValueError("gen_asset_image workflow must be an object")
    definition = workflow.get("definition")
    if not isinstance(definition, Mapping):
        raise ValueError("gen_asset_image workflow definition must be an object")
    prompt_path = _required_text(workflow.get("prompt_path"), "workflow.prompt_path")
    seed_path = _required_text(workflow.get("seed_path"), "workflow.seed_path")
    output_node = _required_text(workflow.get("output_node"), "workflow.output_node")
    return definition, prompt_path, seed_path, output_node


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
        try:
            raw_message = await websocket.recv()
        except ConnectionClosed as exc:
            raise RuntimeError("Comfy websocket closed before a terminal message") from exc

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


def _history_image(
    history: Mapping[str, Any], *, prompt_id: str, output_node: str
) -> tuple[str, str, str]:
    entry = history.get(prompt_id)
    if not isinstance(entry, Mapping):
        raise ValueError("Comfy history is missing the submitted prompt")
    status = entry.get("status")
    status_success = (
        status == "success"
        or (
            isinstance(status, Mapping)
            and status.get("status_str") == "success"
        )
    )
    if not status_success:
        raise ValueError("Comfy history status is not successful")
    outputs = entry.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("Comfy history outputs must be an object")
    output = outputs.get(output_node)
    if not isinstance(output, Mapping):
        raise ValueError("Comfy history is missing the bound output node")
    images = output.get("images")
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("Comfy bound output must contain exactly one image")
    image = images[0]
    if not isinstance(image, Mapping):
        raise ValueError("Comfy history image must be an object")
    filename = _required_text(image.get("filename"), "Comfy image.filename")
    subfolder = image.get("subfolder")
    if not isinstance(subfolder, str):
        raise ValueError("Comfy image.subfolder must be text")
    media_type = _required_text(image.get("type"), "Comfy image.type")
    return filename, subfolder, media_type


async def _run_comfy(
    comfy: ComfyClient,
    *,
    workflow: Mapping[str, Any],
    client_id: str,
    output_node: str,
    context: WorkerContext,
    generated: list[GeneratedPng],
) -> bool:
    submit_attempted = False
    free_error: BaseException | None = None
    try:
        async with comfy.connect_ws(client_id) as websocket:
            submit_attempted = True
            submit_response = await comfy.submit(
                prompt=workflow,
                client_id=client_id,
                prompt_id=client_id,
            )
            returned_prompt_id = submit_response.get("prompt_id")
            if returned_prompt_id != client_id:
                raise ValueError(
                    "Comfy submit returned a prompt id different from the request"
                )
            interrupted = await _consume_websocket(
                websocket,
                prompt_id=client_id,
                context=context,
            )
            if interrupted:
                return True
            history = await comfy.history(client_id)
            filename, subfolder, media_type = _history_image(
                history,
                prompt_id=client_id,
                output_node=output_node,
            )
            generated.append(
                await write_generated_png(
                    comfy.view_stream(
                        filename=filename,
                        subfolder=subfolder,
                        media_type=media_type,
                    ),
                    data_dir=settings.DATA_DIR,
                )
            )
            return False
    finally:
        primary_error = sys.exc_info()[1]
        if submit_attempted:
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
        if free_error is not None:
            if primary_error is not None:
                raise ComfyResourceError(
                    f"Comfy primary error: {primary_error}; "
                    f"Comfy free error: {free_error}"
                ) from primary_error
            raise ComfyResourceError(
                f"Comfy free error: {free_error}"
            ) from free_error


def _combine_cleanup_error(
    primary_error: BaseException | None, cleanup_error: OSError
) -> None:
    if primary_error is not None:
        raise RuntimeError(
            f"{primary_error}; temporary file cleanup failed: {cleanup_error}"
        ) from primary_error
    raise RuntimeError(f"temporary file cleanup failed: {cleanup_error}") from cleanup_error


async def gen_asset_image_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    snapshot = _snapshot(task)
    input_hash = _required_text(task.payload.get("input_hash"), "input_hash")
    cached_prompt = snapshot.get("cached_prompt")
    if cached_prompt is not None and not isinstance(cached_prompt, str):
        raise ValueError("gen_asset_image cached_prompt must be text or null")

    if await _cancel_safe_point(context):
        return

    vllm = VLLMClient(str(settings.VLLM_BASE_URL))
    if cached_prompt is None:
        rendered_prompt = _required_text(
            snapshot.get("rendered_prompt"), "rendered_prompt"
        )
        model = _required_text(snapshot.get("model"), "model")
        temperature = _temperature(snapshot.get("temperature"))
        schema = _guided_schema(snapshot)
        await vllm.wake()
        response = await vllm.structured_chat(
            messages=[{"role": "user", "content": rendered_prompt}],
            model=model,
            temperature=temperature,
            schema_name="zimage",
            schema=schema,
        )
        built_prompt = _built_prompt(response)
        cache_state = "miss"
    else:
        built_prompt = _required_text(cached_prompt, "cached_prompt")
        cache_state = "hit"

    logger.info(
        "gen_asset_image prompt built task_id=%s cache=%s input_hash=%s built_prompt=%s",
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
        return
    await vllm.sleep()

    definition, prompt_path, seed_path, output_node = _workflow(snapshot)
    seed = _seed(snapshot.get("seed"))
    client_id = _required_text(
        snapshot.get("comfy_prompt_id"), "comfy_prompt_id"
    )
    injected_workflow = inject_zimage_workflow_inputs(
        definition,
        prompt_path=prompt_path,
        seed_path=seed_path,
        built_prompt=built_prompt,
        seed=seed,
    )

    generated: list[GeneratedPng] = []
    try:
        interrupted = await _run_comfy(
            ComfyClient(str(settings.COMFY_BASE_URL)),
            workflow=injected_workflow,
            client_id=client_id,
            output_node=output_node,
            context=context,
            generated=generated,
        )
        if interrupted:
            await context.cancel_safe_point()
            return
        if await _cancel_safe_point(context):
            return
        if len(generated) != 1:
            raise RuntimeError("Comfy pipeline produced no validated PNG")
        async with async_session_factory() as session:
            completed = await commit_generated_asset_image(
                session,
                context.queue,
                task,
                generated[0],
                built_prompt=built_prompt,
                data_dir=settings.DATA_DIR,
            )
        if completed is not None:
            await context.queue.publish_committed(completed)
    finally:
        primary_error = sys.exc_info()[1]
        for generated_png in generated:
            try:
                cleanup_generated_png(generated_png, data_dir=settings.DATA_DIR)
            except OSError as exc:
                _combine_cleanup_error(primary_error, exc)
