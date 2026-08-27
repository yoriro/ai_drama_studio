from pydantic import BaseModel, ConfigDict, Field


class GenerateAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)


class GenerateShotsImpactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clips_count: int = Field(ge=0)
    videos_count: int = Field(ge=0)
    confirm_token: str | None
    expires_in: int | None
