from app.core.config import settings
from app.services.gen_shots import extract_shots
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


async def gen_shots_handler(task: ClaimedTask, context: WorkerContext) -> None:
    result = await extract_shots(
        task,
        context,
        VLLMClient(str(settings.VLLM_BASE_URL)),
    )
    if result is None:
        return
