from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Secrets come from the environment only (never committed)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field("development", pattern="^(development|test|production)$")
    database_url: str = "postgresql+psycopg://career:career@localhost:5432/career_agent"
    redis_url: str = "redis://localhost:6379/0"

    # 32+ random bytes, base64/hex/any string; used to sign JWTs.
    jwt_secret: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    # Master key for envelope encryption of stored tokens (urlsafe base64 of 32 bytes).
    master_key: str = Field(..., min_length=40)
    master_key_version: int = 1

    cookie_secure: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]
    login_rate_limit_per_minute: int = 5
    timezone: str = "Asia/Karachi"

    @field_validator("cookie_secure")
    @classmethod
    def _secure_in_prod(cls, v: bool, info):  # noqa: ANN001
        if info.data.get("app_env") == "production" and not v:
            raise ValueError("COOKIE_SECURE must be true in production")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
