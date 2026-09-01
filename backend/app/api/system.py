from fastapi import APIRouter, Request

from app.schemas.system import HealthResponse
from app.services.system_health import build_health_response

router = APIRouter(prefix="/system")


@router.get("/health", response_model=HealthResponse, summary="System health")
async def get_health(request: Request) -> HealthResponse:
    return await build_health_response(
        vllm_probe=request.app.state.vllm_client.health,
        comfy_probe=request.app.state.comfy_client.health,
        zimage_hash=request.app.state.workflow_binding_snapshot.workflow_hash,
        minimaxh3_hash=(
            request.app.state.minimax_workflow_binding_snapshot.workflow_hash
        ),
    )
