"""Structured (JSON-lines) logging for the API and the scheduler.

Every record carries the request id of the HTTP request (or pipeline run) it belongs to, and every message, argument
and traceback goes through redact() so a credential can never reach a log file."""

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime

from app.core.redact import redact

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_STD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                out[k] = redact(v) if isinstance(v, str) else v
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str, ensure_ascii=False)


class RedactingTextFormatter(logging.Formatter):
    """Human-readable variant for a terminal (LOG_FORMAT=text); still redacted."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure(service: str) -> None:
    """Idempotent. LOG_LEVEL (default INFO) and LOG_FORMAT (json|text, default json) come from the environment."""
    root = logging.getLogger()
    if getattr(root, "_career_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(RedactingTextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(RedactingJsonFormatter())
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    # uvicorn's own access log would duplicate ours (and print query strings); keep its errors only
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    root._career_configured = True  # type: ignore[attr-defined]
    logging.getLogger("app").info("logging configured", extra={"service": service})
