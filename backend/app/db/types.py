"""Column types that are native on PostgreSQL and degrade gracefully on SQLite (unit tests)."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

JSONType = JSON().with_variant(JSONB(), "postgresql")

EMBEDDING_DIM = 1024


class Embedding(TypeDecorator):
    """pgvector `vector(dim)` on PostgreSQL, JSON list elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is not None and len(value) != self.dim:
            raise ValueError(f"embedding must have {self.dim} dimensions, got {len(value)}")
        return value

    def process_result_value(self, value, dialect):
        return None if value is None else [float(x) for x in value]
