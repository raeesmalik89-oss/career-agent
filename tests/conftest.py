"""Test harness.

Unit/integration tests run on SQLite (no Docker needed) by applying the real Alembic migrations.
Set TEST_DATABASE_URL=postgresql+psycopg://... to run the same suite plus `postgres`-marked tests on PostgreSQL.
"""

import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.enums import Actor, Role  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.schemas.settings import UserSettings  # noqa: E402
from app.services import settings_service  # noqa: E402
from app.services.seed import seed_sources  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PG_URL = os.environ.get("TEST_DATABASE_URL")
OWNER_PASSWORD = "correct-horse-battery-staple"


def pytest_collection_modifyitems(config, items):
    if PG_URL:
        return
    skip = pytest.mark.skip(reason="set TEST_DATABASE_URL to run PostgreSQL-only tests")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


def alembic_upgrade(connection) -> None:
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "backend", "migrations"))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    if PG_URL:
        if "test" not in PG_URL.rsplit("/", 1)[-1]:
            raise RuntimeError("TEST_DATABASE_URL must point at a database whose name contains 'test' (it is wiped)")
        eng = create_engine(PG_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    else:
        db_file = tmp_path_factory.mktemp("db") / "test.db"
        eng = create_engine(f"sqlite:///{db_file}")

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            # pysqlite starts transactions lazily, which breaks SAVEPOINT-based test isolation: a commit inside a
            # test would persist. Let SQLAlchemy emit BEGIN itself (documented SQLAlchemy recipe).
            dbapi_conn.isolation_level = None

        @event.listens_for(eng, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")

    with eng.begin() as conn:
        alembic_upgrade(conn)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """Each test runs inside a transaction that is rolled back afterwards."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client(db):
    from app.api.v1.auth import login_limiter
    from app.main import app

    login_limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, role: Role = Role.owner, email: str | None = None) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        display_name="Test User",
        role=role,
        password_hash=hash_password(OWNER_PASSWORD),
    )
    db.add(user)
    db.flush()
    settings_service.save(db, user.id, UserSettings(), actor=Actor.system)
    db.commit()
    return user


@pytest.fixture
def owner(db) -> User:
    return make_user(db, Role.owner)


@pytest.fixture
def viewer(db) -> User:
    return make_user(db, Role.viewer)


@pytest.fixture
def seeded(db):
    seed_sources(db)
    db.commit()


def login(client, user: User, **extra) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": user.email, "password": OWNER_PASSWORD, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


__all__ = ["OWNER_PASSWORD", "login", "make_user", "sessionmaker"]
