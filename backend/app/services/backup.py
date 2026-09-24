"""Daily backups of the local SQLite database (storage/backups/).

Uses SQLite's online backup API, so the copy is consistent even while the API or the scheduler is writing, then
checks the copy with PRAGMA quick_check and keeps the newest `backup_keep` files. PostgreSQL deployments are backed
up with pg_dump (see README); for them this module reports that it does nothing.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings

PREFIX = "career-agent-"
DAILY = timedelta(hours=20)  # "once a day" with slack for a scheduler that started late


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    size: int
    created_at: datetime


def sqlite_path(database_url: str | None = None) -> Path | None:
    url = make_url(database_url or get_settings().database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def backup_dir() -> Path:
    return Path(get_settings().storage_dir) / "backups"


def list_backups(directory: Path | None = None) -> list[BackupInfo]:
    d = directory or backup_dir()
    if not d.is_dir():
        return []
    files = [
        BackupInfo(p, p.stat().st_size, datetime.fromtimestamp(p.stat().st_mtime, UTC))
        for p in d.glob(f"{PREFIX}*.db")
        if p.is_file()
    ]
    return sorted(files, key=lambda b: b.created_at, reverse=True)


def create_backup(
    source: Path | None = None, directory: Path | None = None, keep: int | None = None, now: datetime | None = None
) -> BackupInfo:
    src = source or sqlite_path()
    if src is None:
        raise BackupError("not a SQLite database; back up PostgreSQL with pg_dump")
    if not src.is_file():
        raise BackupError(f"database file not found: {src}")
    d = directory or backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(UTC)
    target = d / f"{PREFIX}{now.strftime('%Y%m%d-%H%M%S')}.db"
    tmp = target.with_suffix(".part")
    # closing(): sqlite3's own context manager only commits; Windows cannot rename a file that is still open
    with (
        closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=30)) as s,
        closing(sqlite3.connect(tmp)) as t,
    ):
        s.backup(t)
        result = t.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise BackupError(f"backup failed its integrity check: {result}")
    tmp.replace(target)
    prune(d, keep or get_settings().backup_keep)
    return BackupInfo(target, target.stat().st_size, now)


def prune(directory: Path, keep: int) -> list[Path]:
    removed = []
    for b in list_backups(directory)[keep:]:
        b.path.unlink(missing_ok=True)
        removed.append(b.path)
    return removed


def due(now: datetime | None = None, directory: Path | None = None) -> bool:
    latest = list_backups(directory)
    return not latest or (now or datetime.now(UTC)) - latest[0].created_at >= DAILY
