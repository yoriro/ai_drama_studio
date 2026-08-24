from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class PromptTemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str

    @field_validator("content")
    @classmethod
    def require_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    content: str
    updated_at: datetime
