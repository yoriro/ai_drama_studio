from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    style_id: int

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    style_id: int | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("style_id")
    @classmethod
    def require_style_id(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("style_id must not be null")
        return value

    @model_validator(mode="after")
    def require_field(self) -> "ProjectPatch":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include a project field")
        return self


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    style_id: int
    created_at: datetime
