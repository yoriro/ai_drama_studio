from app.core.config import settings
from app.services.gen_assets import extract_assets
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


async def gen_assets_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    await extract_assets(
        task,
        context,
        VLLMClient(str(settings.VLLM_BASE_URL)),
    )
