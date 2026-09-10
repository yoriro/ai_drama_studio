from datetime import datetime

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Style(Base):
    __tablename__ = "styles"
    __table_args__ = (UniqueConstraint("name", name="uq_styles_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    prompt_fragment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    style_id: Mapped[int] = mapped_column(
        ForeignKey("styles.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("key", name="uq_prompt_templates_key"),
        CheckConstraint(
            "key IN ('script2assets', 'script2shots', 'zimage', 'minimaxh3')",
            name="ck_prompt_templates_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_episodes_project_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    script_text: Mapped[str] = mapped_column(Text, nullable=False)
    script_revision: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )
    assets_generated_script_revision: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    shots_generated_script_revision: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "type IN ('character', 'scene', 'prop')", name="ck_assets_type"
        ),
        CheckConstraint(
            "source IN ('generated', 'manual')", name="ck_assets_source"
        ),
        UniqueConstraint("project_id", "name", name="uq_assets_project_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )
    image_prompt_cache: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_prompt_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssetImage(Base):
    __tablename__ = "asset_images"
    __table_args__ = (
        CheckConstraint(
            "source IN ('generated', 'uploaded')", name="ck_asset_images_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    built_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Shot(Base):
    __tablename__ = "shots"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "order_index", name="uq_shots_episode_order_index"
        ),
        CheckConstraint(
            "status IN ('normal', 'changed')", name="ck_shots_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_est: Mapped[float] = mapped_column(DOUBLE_PRECISION, nullable=False)
    shot_type: Mapped[str] = mapped_column(String, nullable=False)
    camera: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShotAsset(Base):
    __tablename__ = "shot_assets"

    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shots.id"), primary_key=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        CheckConstraint(
            "generation_mode IN ('ref2v', 'fl2v', 'context_loop')",
            name="ck_clips_generation_mode",
        ),
        CheckConstraint(
            "generation_state IN ('empty', 'queued', 'generating', 'ready', 'failed')",
            name="ck_clips_generation_state",
        ),
        CheckConstraint(
            "freshness IN ('fresh', 'stale')", name="ck_clips_freshness"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id"), nullable=False
    )
    generation_mode: Mapped[str] = mapped_column(
        String, server_default=text("'ref2v'"), nullable=False
    )
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_duration: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_cache: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_state: Mapped[str] = mapped_column(
        String, server_default=text("'empty'"), nullable=False
    )
    freshness: Mapped[str] = mapped_column(
        String, server_default=text("'fresh'"), nullable=False
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClipShot(Base):
    __tablename__ = "clip_shots"
    __table_args__ = (
        UniqueConstraint("shot_id", name="uq_clip_shots_shot"),
        UniqueConstraint("clip_id", "position", name="uq_clip_shots_position"),
    )

    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True
    )
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("shots.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ClipRefSlot(Base):
    __tablename__ = "clip_ref_slots"
    __table_args__ = (
        UniqueConstraint(
            "clip_id", "slot_no", name="uq_clip_ref_slots_clip_slot"
        ),
        CheckConstraint(
            "slot_no >= 1 AND slot_no <= 9", name="ck_clip_ref_slots_slot_no"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    slot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    asset_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    asset_type_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    override_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )


class ClipVideo(Base):
    __tablename__ = "clip_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_duration: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_duration: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    built_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "type IN ('gen_assets', 'gen_shots', 'gen_asset_image', 'gen_clip_video')",
            name="ck_tasks_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'canceled')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 1", name="ck_tasks_progress"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    progress: Mapped[float] = mapped_column(DOUBLE_PRECISION, nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


Index(
    "uq_asset_images_current",
    AssetImage.asset_id,
    unique=True,
    postgresql_where=text("is_current = true"),
)
Index(
    "uq_clip_videos_current",
    ClipVideo.clip_id,
    unique=True,
    postgresql_where=text("is_current = true"),
)
Index(
    "uq_tasks_active_target",
    Task.type,
    Task.target_id,
    unique=True,
    postgresql_where=text(
        "status IN ('queued', 'running') "
        "AND type IN ('gen_assets', 'gen_shots')"
    ),
)
Index(
    "uq_tasks_active_request_id",
    Task.request_id,
    unique=True,
    postgresql_where=text("status IN ('queued', 'running') AND request_id IS NOT NULL"),
)


__all__ = [
    "Asset",
    "AssetImage",
    "Clip",
    "ClipRefSlot",
    "ClipShot",
    "ClipVideo",
    "Episode",
    "Project",
    "PromptTemplate",
    "Shot",
    "ShotAsset",
    "Style",
    "Task",
]
