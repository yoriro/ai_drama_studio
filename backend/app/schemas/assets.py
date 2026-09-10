from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


AssetType = Literal["character", "scene"]
MAX_ASSET_NAME_BYTES = 2000


def _normalize_asset_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("name must not be blank")
    if "\x00" in normalized:
        raise ValueError("name must not contain NUL")
    if len(normalized.encode("utf-8")) > MAX_ASSET_NAME_BYTES:
        raise ValueError("name is too long")
    return normalized


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AssetType
    name: str
    description: str

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_asset_name(value)

    @field_validator("description")
    @classmethod
    def require_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name must not be null")
        return _normalize_asset_name(value)

    @field_validator("description")
    @classmethod
    def require_description(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("description must not be null")
        if not value.strip():
            raise ValueError("description must not be blank")
        return value

    @model_validator(mode="after")
    def require_field(self) -> "AssetPatch":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include an asset field")
        return self


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    type: str
    name: str
    description: str
    source: str
    revision: int
    created_at: datetime
    updated_at: datetime


class AssetImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    sha256: str
    seed: str | None
    source: str
    is_current: bool
    created_at: datetime

    @field_validator("seed", mode="before")
    @classmethod
    def serialize_seed(cls, value: int | str | None) -> str | None:
        if value is None:
            return None
        return str(value)


class CurrentImagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: int
