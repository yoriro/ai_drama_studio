from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ImageStorageFormat:
    extension: str
    mime_type: str


_IMAGE_STORAGE_FORMATS = {
    "PNG": ImageStorageFormat("png", "image/png"),
    "JPEG": ImageStorageFormat("jpg", "image/jpeg"),
    "WEBP": ImageStorageFormat("webp", "image/webp"),
}


def image_storage_format(image_format: str) -> ImageStorageFormat:
    try:
        return _IMAGE_STORAGE_FORMATS[image_format.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported image format: {image_format}") from exc


def asset_image_relative_path(
    project_id: int, asset_id: int, image_id: int, extension: str
) -> Path:
    if min(project_id, asset_id, image_id) <= 0:
        raise ValueError("asset image identifiers must be positive")
    if extension not in {"png", "jpg", "webp"}:
        raise ValueError(f"Unsupported image extension: {extension}")
    return Path(
        "projects",
        str(project_id),
        "assets",
        str(asset_id),
        f"{image_id}.{extension}",
    )


def asset_image_path(
    data_dir: Path, project_id: int, asset_id: int, image_id: int, extension: str
) -> Path:
    return data_dir.resolve() / asset_image_relative_path(
        project_id, asset_id, image_id, extension
    )


def temporary_asset_image_path(data_dir: Path) -> Path:
    return data_dir.resolve() / "tmp" / "asset-images" / f"{uuid4().hex}.upload"


def asset_image_trash_path(
    data_dir: Path, project_id: int, asset_id: int, image_id: int, extension: str
) -> Path:
    return data_dir.resolve() / "trash" / asset_image_relative_path(
        project_id, asset_id, image_id, extension
    )


def resolve_data_path(data_dir: Path, relative_path: str | Path) -> Path:
    root = data_dir.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("storage path is outside DATA_DIR") from exc
    return candidate


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
