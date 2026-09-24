"""Removes secrets from text before it is logged or stored (agent errors, pipeline errors, log lines).

Deliberately aggressive: a false positive only hides part of a message; a false negative leaks a credential."""

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization headers and bearer tokens
    (re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [redacted]"),
    # JWTs (three base64url segments)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[redacted-jwt]"),
    # Telegram bot tokens (also inside https://api.telegram.org/bot<token>/...)
    # (no \b at the start: in API URLs the token directly follows "bot")
    (re.compile(r"(?<![0-9])\d{6,12}:[A-Za-z0-9_-]{30,}"), "[redacted-bot-token]"),
    # GitHub tokens
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[redacted-github-token]"),
    # OpenAI / Anthropic style keys
    (re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{16,}\b"), "[redacted-api-key]"),
    # key=value / "key": "value" pairs whose name says secret
    (
        re.compile(
            r"(?i)([\"']?\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|secret|password|passwd|pwd|"
            r"client[_-]?secret|private[_-]?key|authorization)\b[\"']?\s*[:=]\s*[\"']?)([^\s\"'&,;}]{4,})"
        ),
        r"\1[redacted]",
    ),
    # credentials inside URLs: scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^@\s/]+@"), r"\1:[redacted]@"),
    # Jooble puts the key in the path: https://pk.jooble.org/api/<key>
    (re.compile(r"(?i)(jooble\.org/api/)[A-Za-z0-9-]{8,}"), r"\1[redacted]"),
]


def redact(text: str | None) -> str:
    if not text:
        return text or ""
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text
