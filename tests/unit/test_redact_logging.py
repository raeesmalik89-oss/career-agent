import json
import logging
import uuid

import pytest

from agents.base import AgentContext
from app.config import Settings
from app.core.checks import config_checks, enforce
from app.core.logging import RedactingJsonFormatter, request_id_var
from app.core.redact import redact

# Fake credentials shaped like real ones (never real values)
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
TG = "1234567890:" + "AAH" + "x" * 32
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


@pytest.mark.parametrize(
    "raw, secret",
    [
        (f"GET https://api.github.com/user failed with token {GH}", GH),
        (f"POST https://api.telegram.org/bot{TG}/sendMessage: 401", TG),
        (f"Authorization: Bearer {JWT}", JWT),
        ("api_key=abcd1234efgh5678 was rejected", "abcd1234efgh5678"),
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ("postgresql://career:s3cretpass@db:5432/x", "s3cretpass"),
        ("https://pk.jooble.org/api/0a1b2c3d-4e5f-6789-abcd-ef0123456789", "0a1b2c3d-4e5f-6789-abcd-ef0123456789"),
        ("key sk-ant-api03-abcdefghijklmnop1234 leaked", "sk-ant-api03-abcdefghijklmnop1234"),
    ],
)
def test_redact_removes_credentials(raw, secret):
    out = redact(raw)
    assert secret not in out and "redacted" in out


def test_redact_keeps_ordinary_text():
    text = "Scanned 198 postings from remotive, 28 new; job 8db3f283 scored 71.3"
    assert redact(text) == text


def test_json_log_lines_are_redacted_and_carry_the_request_id():
    fmt = RedactingJsonFormatter()
    token = request_id_var.set("req-123")
    try:
        try:
            raise RuntimeError(f"telegram said no to {TG}")
        except RuntimeError:
            rec = logging.getLogger("t").makeRecord("t", logging.ERROR, __file__, 1, "sending with %s", (GH,), None)
            rec.exc_info = __import__("sys").exc_info()
            line = json.loads(fmt.format(rec))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req-123" and line["level"] == "ERROR"
    assert GH not in line["msg"] and TG not in line["exc"]


def test_agent_errors_are_redacted_before_storage():
    ctx = AgentContext(uuid.uuid4(), db=None, user_id=None)  # type: ignore[arg-type]
    ctx.error("github_failed", f"clone of https://x:{GH}@github.com/a/b failed")
    assert GH not in ctx.errors[0].message


def _settings(**kw) -> Settings:
    base = {"jwt_secret": "Zq8-uP3rT7vW1yB4nM6kL9jH2gF5dS0aX", "master_key": "A" * 43 + "="}
    return Settings(_env_file=None, **{**base, **kw})  # type: ignore[call-arg]


def test_config_checks():
    assert config_checks(_settings(app_env="development", cookie_secure=False)) == []
    weak = _settings(
        app_env="production", cookie_secure=True, jwt_secret="x" * 40, database_url="postgresql+psycopg://u:p@h/d"
    )
    assert {c.code for c in config_checks(weak)} >= {"weak_jwt_secret", "metrics_open"}
    with pytest.raises(RuntimeError, match="refusing to start"):
        enforce(weak)
    enforce(_settings(app_env="development", jwt_secret="x" * 40))  # development only reports
