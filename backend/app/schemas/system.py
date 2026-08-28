from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "unhealthy"]
    message: str | None = None


class WorkflowBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["valid"]
    message: str | None = None
    hashes: dict[str, str]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vllm: HealthComponent
    comfy: HealthComponent
    workflow_bindings: WorkflowBindings
