import os

from alembic import context
from sqlalchemy import create_engine

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _render_item(type_, obj, autogen_context):
    if type_ == "type" and obj.__class__.__module__ == "app.db.types":
        autogen_context.imports.add("import app.db.types")
        return f"app.db.types.{obj.__class__.__name__}()"
    return False


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_item=_render_item)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")  # provided by tests
    if connection is not None:
        _run(connection)
        return
    with create_engine(_url()).connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=_render_item,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
