from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.schemas.generation import CameraType, ShotType


class ShotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_type: ShotType | None = None
    camera: CameraType | None = None
    description: str | None = None
    dialogue: str | None = None
    asset_ids: list[StrictInt] | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ShotPatch":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include a shot field")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        if self.asset_ids is not None:
            if any(asset_id <= 0 for asset_id in self.asset_ids):
                raise ValueError("asset_ids must contain positive integers")
            if len(self.asset_ids) != len(set(self.asset_ids)):
                raise ValueError("asset_ids must not contain duplicates")
        return self


class ShotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    episode_id: int = Field(gt=0)
    order_index: int = Field(ge=1)
    duration_est: float = Field(ge=1, le=5)
    shot_type: ShotType
    camera: CameraType
    description: str
    dialogue: str
    asset_ids: list[int]
    status: Literal["normal", "changed"]
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
