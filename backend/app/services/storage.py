"""Content-addressed local file storage (S3-compatible backend comes with production deployment)."""

from pathlib import Path

from app.config import get_settings


def root() -> Path:
    path = Path(get_settings().storage_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_document(data: bytes, sha256: str, ext: str) -> str:
    """Store bytes under documents/<sha256><ext>; returns the storage URI (relative path)."""
    if not ext.startswith(".") or not ext[1:].isalnum() or len(sha256) != 64:
        raise ValueError("invalid document name")
    rel = f"documents/{sha256}{ext.lower()}"
    target = root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return rel


def resolve(uri: str) -> Path:
    base = root()
    path = (base / uri).resolve()
    if base not in path.parents:
        raise ValueError("path escapes storage root")
    return path
