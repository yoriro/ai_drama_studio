import json
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from app.schemas.assets import _normalize_asset_name
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


class GeneratedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    existing_id: StrictInt | None
    type: Literal["character", "scene"]
    name: StrictStr
    description: StrictStr

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_asset_name(value)


class GeneratedAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assets: list[GeneratedAsset]


GENERATED_ASSETS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "existing_id": {"type": ["integer", "null"]},
                    "type": {
                        "type": "string",
                        "enum": ["character", "scene"],
                    },
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["existing_id", "type", "name", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assets"],
    "additionalProperties": False,
}


def _snapshot(task: ClaimedTask) -> dict[str, object]:
    payload = task.payload
    snapshot = payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_assets input_snapshot must be an object")
    return snapshot


def _response_content(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("vLLM response must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("vLLM choice must be an object")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("vLLM choice message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("vLLM response content must be a non-empty string")
    return content


async def extract_assets(
    task: ClaimedTask,
    context: WorkerContext,
    client: VLLMClient,
) -> GeneratedAssetsResponse | None:
    snapshot = _snapshot(task)
    rendered_prompt = snapshot.get("rendered_prompt")
    model = snapshot.get("model")
    temperature = snapshot.get("temperature")
    if not isinstance(rendered_prompt, str):
        raise ValueError("gen_assets rendered_prompt must be a string")
    if not isinstance(model, str) or not model:
        raise ValueError("gen_assets model must be a non-empty string")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ValueError("gen_assets temperature must be a number")

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
        schema_name="script2assets",
        schema=GENERATED_ASSETS_SCHEMA,
    )
    after_external = await context.cancel_safe_point()
    if after_external.task is not None and after_external.task.status == "canceled":
        return None
    try:
        parsed = json.loads(_response_content(response))
        return GeneratedAssetsResponse.model_validate(parsed)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ValueError("vLLM response is not a valid script2assets JSON object") from exc
