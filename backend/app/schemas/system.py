from typing import Literal

from pydantic import BaseModel


class HealthComponent(BaseModel):
    status: Literal["not_checked"]


class WorkflowBindings(HealthComponent):
    hashes: dict[str, str]


class HealthResponse(BaseModel):
    vllm: HealthComponent
    comfy: HealthComponent
    workflow_bindings: WorkflowBindings
