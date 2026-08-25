from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TaskType = Literal[
    "gen_assets",
    "gen_shots",
    "gen_asset_image",
    "gen_clip_video",
]
TaskStatus = Literal["queued", "running", "done", "failed", "canceled"]


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int = Field(gt=0)
    type: TaskType
    target_id: int
    request_id: str | None
    status: TaskStatus
    progress: float = Field(ge=0, le=1)
    error_msg: str | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
