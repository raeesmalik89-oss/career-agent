"""Configuration checks run at startup and shown on the System health panel.

In production a 'fail' stops the API from starting; in development everything is only reported."""

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class Check:
    level: str  # fail | warn
    code: str
    message: str


def config_checks(s: Settings) -> list[Check]:
    out: list[Check] = []
    prod = s.app_env == "production"
    if len(set(s.jwt_secret)) < 12:
        out.append(
            Check("fail", "weak_jwt_secret", "JWT_SECRET has too little variety; generate one with app.cli gen-keys")
        )
    if "*" in s.cors_origins:
        out.append(Check("fail", "cors_wildcard", "CORS_ORIGINS must list exact origins, not *"))
    if prod and not s.cookie_secure:  # off is normal on http://localhost
        out.append(Check("fail", "cookie_not_secure", "COOKIE_SECURE must be true on a server (HTTPS)"))
    if prod and s.database_url.startswith("sqlite"):
        out.append(
            Check("warn", "sqlite_in_production", "SQLite is meant for one local user; use PostgreSQL on a server")
        )
    if prod and not s.metrics_token:
        out.append(Check("warn", "metrics_open", "Set METRICS_TOKEN so /metrics needs a bearer token"))
    if s.access_token_minutes > 60:
        out.append(
            Check("warn", "long_access_tokens", "ACCESS_TOKEN_MINUTES above 60 widens the window of a stolen token")
        )
    return out


def enforce(s: Settings) -> None:
    fails = [c for c in config_checks(s) if c.level == "fail"]
    if s.app_env == "production" and fails:
        raise RuntimeError("refusing to start: " + "; ".join(c.message for c in fails))
