"""Content-addressed local file storage (S3-compatible backend comes with production deployment)."""

import logging
import tempfile
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("app.storage")
_warned_fallback: set[str] = set()


def root() -> Path:
    """The writable storage directory.

    Uses STORAGE_DIR when it exists and is writable. On a host where that path is not writable (e.g. a
    container whose working directory is root-owned while the app runs as a non-root user), fall back to a
    writable temp directory so uploads keep working instead of failing with a 500. The data there is not
    durable across restarts, but the app stays usable without any extra configuration.
    """
    configured = Path(get_settings().storage_dir)
    try:
        configured = configured.resolve()
        configured.mkdir(parents=True, exist_ok=True)
        return configured
    except OSError as exc:
        fallback = (Path(tempfile.gettempdir()) / "career-agent-storage").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        if str(fallback) not in _warned_fallback:
            _warned_fallback.add(str(fallback))
            logger.warning("storage_dir %s is not writable (%s); using %s instead", configured, exc, fallback)
        return fallback


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
