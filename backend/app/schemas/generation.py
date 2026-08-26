from pydantic import BaseModel, ConfigDict, Field


class GenerateAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)
