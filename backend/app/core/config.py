from pathlib import Path

from pydantic import AnyHttpUrl, Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    DATABASE_URL: PostgresDsn = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_drama_studio"
    )
    DATA_DIR: Path = Path("./data")
    VLLM_BASE_URL: AnyHttpUrl = "http://localhost:8001"
    VLLM_MODEL: str = Field(default="Qwen/Qwen2.5-7B-Instruct", min_length=1)
    COMFY_BASE_URL: AnyHttpUrl = "http://localhost:8188"
    SCRIPT_CHAR_LIMIT: int = Field(default=2000, gt=0)
    CLIP_MAX_SECONDS: int = Field(default=15, gt=0)
    CLIP_MIN_SECONDS: int = Field(default=5, gt=0)
    SLOT_HARD_LIMIT: int = Field(default=9, gt=0)
    SLOT_SOFT_LIMIT: int = Field(default=4, gt=0)
    UPLOAD_MAX_MB: int = Field(default=20, gt=0)
    TRASH_RETENTION_HOURS: int = Field(default=24, gt=0)
    DEBUG_PROMPTS: bool = False

    @field_validator("DATABASE_URL")
    @classmethod
    def require_asyncpg_dsn(cls, value: PostgresDsn) -> PostgresDsn:
        if not str(value).startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg scheme")
        return value

    @field_validator("DEBUG_PROMPTS", mode="before")
    @classmethod
    def parse_strict_bool(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("DEBUG_PROMPTS must be true or false")

    @model_validator(mode="after")
    def validate_ranges(self) -> "Settings":
        if self.CLIP_MIN_SECONDS > self.CLIP_MAX_SECONDS:
            raise ValueError("CLIP_MIN_SECONDS must not exceed CLIP_MAX_SECONDS")
        if self.SLOT_SOFT_LIMIT > self.SLOT_HARD_LIMIT:
            raise ValueError("SLOT_SOFT_LIMIT must not exceed SLOT_HARD_LIMIT")
        return self


settings = Settings()
