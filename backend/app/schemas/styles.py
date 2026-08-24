from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class StyleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    prompt_fragment: str

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("prompt_fragment")
    @classmethod
    def require_prompt_fragment(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt_fragment must not be blank")
        return value


class StylePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    prompt_fragment: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("prompt_fragment")
    @classmethod
    def require_prompt_fragment(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("prompt_fragment must not be blank")
        return value

    @model_validator(mode="after")
    def require_field(self) -> "StylePatch":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include a style field")
        return self


class StyleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prompt_fragment: str
    created_at: datetime
    updated_at: datetime
