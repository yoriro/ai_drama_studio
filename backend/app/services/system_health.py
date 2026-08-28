from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from app.schemas.system import HealthComponent, HealthResponse, WorkflowBindings


HealthProbe = Callable[[], Awaitable[object]]


async def probe_health(component: str, probe: HealthProbe) -> HealthComponent:
    try:
        await probe()
    except httpx.HTTPStatusError as exc:
        return HealthComponent(
            status="unhealthy",
            message=f"{component} health returned HTTP {exc.response.status_code}",
        )
    except (httpx.TimeoutException, TimeoutError):
        return HealthComponent(
            status="unhealthy",
            message=f"{component} health probe timed out",
        )
    except (httpx.RequestError, OSError):
        return HealthComponent(
            status="unhealthy",
            message=f"{component} health connection failed",
        )
    except ValueError:
        return HealthComponent(
            status="unhealthy",
            message=f"{component} health response was invalid",
        )
    return HealthComponent(status="healthy", message=None)


async def build_health_response(
    *,
    vllm_probe: HealthProbe,
    comfy_probe: HealthProbe,
    workflow_hash: str,
) -> HealthResponse:
    vllm = await probe_health("vLLM", vllm_probe)
    comfy = await probe_health("ComfyUI", comfy_probe)
    return HealthResponse(
        vllm=vllm,
        comfy=comfy,
        workflow_bindings=WorkflowBindings(
            status="valid",
            message=None,
            hashes={"zimage": workflow_hash},
        ),
    )
