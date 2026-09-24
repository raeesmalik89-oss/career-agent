from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    # SQLite (local dev): the API and the scheduler are separate processes sharing one file, so a writer waits up to
    # 30 s for the other instead of failing at once. No WAL: it needs shared memory, which a Windows drive mounted in
    # WSL (/mnt/e) does not support ("disk I/O error"), and the same file is used from both Windows and WSL.
    engine = create_engine(url, pool_pre_ping=True, connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
