from fastapi import APIRouter

from app.schemas.system import HealthComponent, HealthResponse, WorkflowBindings

router = APIRouter(prefix="/system")


@router.get("/health", response_model=HealthResponse, summary="System health skeleton")
async def get_health() -> HealthResponse:
    return HealthResponse(
        vllm=HealthComponent(status="not_checked"),
        comfy=HealthComponent(status="not_checked"),
        workflow_bindings=WorkflowBindings(status="not_checked", hashes={}),
    )
