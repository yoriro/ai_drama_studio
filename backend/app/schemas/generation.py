from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class GenerateAssetImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_note: StrictStr | None = None
    request_id: StrictStr | None = None


class GenerateAssetImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)


class GenerateAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)


class GenerateShotsImpactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clips_count: int = Field(ge=0)
    videos_count: int = Field(ge=0)
    confirm_token: str | None
    expires_in: int | None


class GenerateShotsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirm_token: StrictStr | None = None

    @field_validator("confirm_token")
    @classmethod
    def require_non_blank_token(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("confirm_token must not be blank")
        return value


class GenerateShotsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)


ShotType = Literal["远景", "全景", "中景", "近景", "特写"]
CameraType = Literal["固定", "推", "拉", "摇", "移", "跟", "手持"]
