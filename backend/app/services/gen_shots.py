import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import Asset, Episode
from app.tasks.queue import ClaimedTask, WorkerContext
from app.services.vllm import VLLMClient


class GeneratedShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order: StrictInt
    duration_est: StrictFloat = Field(ge=1, le=5)
    shot_type: Literal["远景", "全景", "中景", "近景", "特写"]
    camera: Literal["固定", "推", "拉", "摇", "移", "跟", "手持"]
    description: StrictStr
    dialogue: StrictStr
    asset_ids: list[StrictInt]


class GeneratedShotsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shots: list[GeneratedShot]


def _snapshot(task: ClaimedTask) -> dict[str, Any]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_shots input_snapshot must be an object")
    return snapshot


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


def _guided_schema(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    guided = snapshot.get("guided_json_schema")
    if not isinstance(guided, Mapping) or set(guided) != {
        "type",
        "json_schema",
    }:
        raise ValueError("gen_shots guided_json_schema must be a response_format object")
    if guided.get("type") != "json_schema":
        raise ValueError("gen_shots guided_json_schema type must be json_schema")
    json_schema = guided.get("json_schema")
    if not isinstance(json_schema, Mapping) or set(json_schema) != {
        "name",
        "strict",
        "schema",
    }:
        raise ValueError("gen_shots guided_json_schema json_schema is invalid")
    if json_schema.get("name") != "script2shots":
        raise ValueError("gen_shots guided_json_schema name must be script2shots")
    if json_schema.get("strict") is not True:
        raise ValueError("gen_shots guided_json_schema must be strict")
    schema = json_schema.get("schema")
    if not isinstance(schema, Mapping):
        raise ValueError("gen_shots guided_json_schema schema must be an object")
    return schema


def _asset_snapshot(snapshot: Mapping[str, Any]) -> tuple[list[dict[str, Any]], set[int]]:
    assets = snapshot.get("assets")
    if not isinstance(assets, list):
        raise ValueError("gen_shots assets snapshot must be an array")
    parsed: list[dict[str, Any]] = []
    ids: set[int] = set()
    for asset in assets:
        if not isinstance(asset, Mapping) or set(asset) != {
            "id",
            "type",
            "name",
            "description",
        }:
            raise ValueError("gen_shots asset snapshot item is invalid")
        asset_id = asset["id"]
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0:
            raise ValueError("gen_shots asset snapshot id must be positive")
        if asset["type"] not in {"character", "scene"}:
            raise ValueError("gen_shots asset snapshot type is invalid")
        if not isinstance(asset["name"], str) or not isinstance(
            asset["description"], str
        ):
            raise ValueError("gen_shots asset snapshot text is invalid")
        if asset_id in ids:
            raise ValueError("gen_shots asset snapshot contains duplicate ids")
        ids.add(asset_id)
        parsed.append(dict(asset))
    if [asset["id"] for asset in parsed] != sorted(ids):
        raise ValueError("gen_shots asset snapshot ids must be ascending")
    return parsed, ids


async def _validate_current_assets(
    task: ClaimedTask,
    snapshot: Mapping[str, Any],
    referenced_ids: set[int],
) -> None:
    episode_id = snapshot.get("episode_id")
    project_id = snapshot.get("project_id")
    if (
        isinstance(episode_id, bool)
        or not isinstance(episode_id, int)
        or episode_id <= 0
        or episode_id != task.target_id
    ):
        raise ValueError("gen_shots episode_id does not match task target")
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id <= 0:
        raise ValueError("gen_shots project_id must be positive")

    async with async_session_factory() as session:
        episode = await session.get(Episode, task.target_id)
        if episode is None or episode.project_id != project_id:
            raise ValueError("gen_shots target episode no longer belongs to project")
        if not referenced_ids:
            return
        result = await session.execute(
            select(Asset.id, Asset.project_id, Asset.type).where(
                Asset.id.in_(referenced_ids)
            )
        )
        rows = result.all()
        current = {int(row.id): (int(row.project_id), row.type) for row in rows}
    if set(current) != referenced_ids or any(
        project != project_id or asset_type not in {"character", "scene"}
        for project, asset_type in current.values()
    ):
        raise ValueError("gen_shots output asset id is no longer valid for the project")


def _validate_output(
    result: GeneratedShotsResponse,
    snapshot_assets: set[int],
) -> set[int]:
    orders = [shot.order for shot in result.shots]
    if orders != list(range(1, len(result.shots) + 1)):
        raise ValueError("gen_shots output order must be the continuous sequence 1..N")
    referenced_ids: set[int] = set()
    for shot in result.shots:
        if len(shot.asset_ids) != len(set(shot.asset_ids)):
            raise ValueError("gen_shots output contains duplicate asset ids in a shot")
        invalid = set(shot.asset_ids) - snapshot_assets
        if invalid:
            raise ValueError("gen_shots output references an asset outside the snapshot")
        referenced_ids.update(shot.asset_ids)
    return referenced_ids


async def extract_shots(
    task: ClaimedTask,
    context: WorkerContext,
    client: VLLMClient,
) -> GeneratedShotsResponse | None:
    snapshot = _snapshot(task)
    rendered_prompt = snapshot.get("rendered_prompt")
    model = snapshot.get("model")
    temperature = snapshot.get("temperature")
    if not isinstance(rendered_prompt, str):
        raise ValueError("gen_shots rendered_prompt must be a string")
    if not isinstance(model, str) or not model:
        raise ValueError("gen_shots model must be a non-empty string")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ValueError("gen_shots temperature must be a number")
    _schema = _guided_schema(snapshot)
    _, snapshot_asset_ids = _asset_snapshot(snapshot)

    before_external = await context.cancel_safe_point()
    if before_external.task is not None and before_external.task.status == "canceled":
        return None
    await client.wake()
    after_wake = await context.cancel_safe_point()
    if after_wake.task is not None and after_wake.task.status == "canceled":
        return None
    response = await client.structured_chat(
        messages=[{"role": "user", "content": rendered_prompt}],
        model=model,
        temperature=float(temperature),
        schema_name="script2shots",
        schema=_schema,
    )
    after_external = await context.cancel_safe_point()
    if after_external.task is not None and after_external.task.status == "canceled":
        return None
    try:
        parsed = json.loads(_response_content(response))
        result = GeneratedShotsResponse.model_validate(parsed)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ValueError("vLLM response is not a valid script2shots JSON object") from exc
    referenced_ids = _validate_output(result, snapshot_asset_ids)
    await _validate_current_assets(task, snapshot, referenced_ids)
    return result
