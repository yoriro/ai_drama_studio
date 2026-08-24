from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EpisodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(gt=0)
    title: str
    script_text: str = ""

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized


class EpisodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int | None = Field(default=None, gt=0)
    title: str | None = None
    script_text: str | None = None

    @field_validator("seq")
    @classmethod
    def require_seq(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("seq must not be null")
        return value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("title must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized

    @field_validator("script_text")
    @classmethod
    def require_script_text(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("script_text must not be null")
        return value

    @model_validator(mode="after")
    def require_field(self) -> "EpisodePatch":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include an episode field")
        return self


class EpisodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    seq: int
    title: str
    script_text: str
    script_revision: int
    assets_generated_script_revision: int | None
    shots_generated_script_revision: int | None
    created_at: datetime
    updated_at: datetime
