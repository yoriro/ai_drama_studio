from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


POSTGRES_INTEGER_MAX = 2_147_483_647


class ClipPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_ids: list[StrictInt]

    @field_validator("shot_ids")
    @classmethod
    def validate_shot_ids(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("shot_ids must not be empty")
        if any(shot_id <= 0 or shot_id > POSTGRES_INTEGER_MAX for shot_id in value):
            raise ValueError(
                "shot_ids must contain positive PostgreSQL INTEGER values"
            )
        if len(value) != len(set(value)):
            raise ValueError("shot_ids must not contain duplicates")
        return value


class ClipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_ids: list[StrictInt]
    reference_asset_ids: list[StrictInt]
    requested_duration: StrictInt | None = None
    user_note: StrictStr | None = None

    @field_validator("shot_ids", "reference_asset_ids")
    @classmethod
    def validate_id_lists(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("id lists must not be empty")
        if any(item <= 0 or item > POSTGRES_INTEGER_MAX for item in value):
            raise ValueError(
                "id lists must contain positive PostgreSQL INTEGER values"
            )
        if len(value) != len(set(value)):
            raise ValueError("id lists must not contain duplicates")
        return value

    @model_validator(mode="after")
    def reject_null_duration(self) -> "ClipCreateRequest":
        if "requested_duration" in self.model_fields_set:
            if self.requested_duration is None:
                raise ValueError("requested_duration must not be null")
        return self

    @field_validator("user_note")
    @classmethod
    def reject_nul_user_note(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("user_note must not contain U+0000")
        return value


class ClipPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_note: StrictStr | None = None
    requested_duration: StrictInt | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ClipPatchRequest":
        if not self.model_fields_set:
            raise ValueError("PATCH body must include a clip field")
        if (
            "requested_duration" in self.model_fields_set
            and self.requested_duration is None
        ):
            raise ValueError("requested_duration must not be null")
        return self

    @field_validator("user_note")
    @classmethod
    def reject_nul_user_note(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("user_note must not contain U+0000")
        return value


class ClipRuleMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ClipReferenceCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: int = Field(gt=0)
    asset_type: str = Field(min_length=1)
    asset_name: str
    first_shot_id: int = Field(gt=0)
    first_order_index: int = Field(ge=1)
    selected_by_default: bool


class ClipPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: int = Field(gt=0)
    shot_ids: list[int]
    duration_est_total: float
    suggested_requested_duration: int = Field(gt=0)
    reference_candidates: list[ClipReferenceCandidateResponse]
    default_reference_asset_ids: list[int]
    violations: list[ClipRuleMessageResponse]
    warnings: list[ClipRuleMessageResponse]


class ClipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    episode_id: int = Field(gt=0)
    generation_mode: Literal["ref2v"]
    user_note: str | None
    requested_duration: int = Field(gt=0)
    generation_state: Literal["empty", "queued", "generating", "ready", "failed"]
    freshness: Literal["fresh", "stale"]
    revision: int = Field(ge=1)
    shot_ids: list[int]
    start_order_index: int = Field(ge=1)
    end_order_index: int = Field(ge=1)
    enabled_slot_count: int = Field(ge=0)
    warnings: list[ClipRuleMessageResponse]
    created_at: datetime
    updated_at: datetime


class ClipSlotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    clip_id: int = Field(gt=0)
    slot_no: int = Field(ge=1, le=9)
    asset_id: int | None
    asset_name_snapshot: str
    asset_type_snapshot: str
    asset_deleted: bool
    enabled: bool
    image_source: Literal["override", "asset_current"] | None
    image_url: str | None


class ClipSlotsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: int = Field(gt=0)
    items: list[ClipSlotResponse]
    warnings: list[ClipRuleMessageResponse]


class ClipSlotEnabledPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: StrictBool


class ClipSlotMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: ClipSlotResponse
    warnings: list[ClipRuleMessageResponse]
