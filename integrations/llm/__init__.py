"""Free AI providers behind one small client (OpenAI-compatible chat completions, JSON output).

- groq:   https://api.groq.com (free API key; fast Llama models)
- gemini: Google AI Studio's OpenAI-compatible endpoint (free API key)
- ollama: a model running on this computer (no key, nothing leaves the machine)

Only these hosts can be reached (Ollama only on localhost), keys never appear in errors, and responses are parsed
as JSON and size-capped. No third-party SDK: nothing extra to install or audit.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.core.redact import redact


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    default_model: str
    secret: str | None  # name in SECRET_NAMES, or None (local)
    timeout_s: int
    privacy: str


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "groq_api_key", 90,
        "Your career facts and the job text are sent to Groq for each rewrite. Groq states it does not train on "
        "API data. Contact details are never sent.",
    ),
    "gemini": Provider(
        "gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
        "gemini_api_key", 120,
        "Your career facts and the job text are sent to Google. On the free tier Google may use prompts to improve "
        "its products. Contact details are never sent.",
    ),
    "ollama": Provider(
        "ollama", "Ollama (this computer)", "http://127.0.0.1:11434/v1", "llama3.2:3b", None, 600,
        "Runs on this computer: nothing leaves it. Small models are slower and write less well.",
    ),
}  # fmt: skip

ALLOWED_HOSTS = {"api.groq.com", "generativelanguage.googleapis.com", "127.0.0.1", "localhost"}
MAX_RESPONSE = 400_000
FENCE_RX = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def endpoint(provider: Provider, ollama_url: str | None = None) -> str:
    base = (ollama_url.rstrip("/") + "/v1") if provider.key == "ollama" and ollama_url else provider.base_url
    parts = urllib.parse.urlsplit(base)
    host = (parts.hostname or "").lower()
    local = host in ("127.0.0.1", "localhost")
    if host not in ALLOWED_HOSTS or (parts.scheme != "https" and not local):
        raise LLMError(f"refusing to call {parts.scheme}://{host}: not an allowed AI provider")
    return base + "/chat/completions"


def parse_json(content: str) -> dict:
    """Models sometimes wrap JSON in ``` fences or add a sentence around it; take the outermost object."""
    text = FENCE_RX.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("the AI did not return JSON")
    try:
        out = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"the AI returned malformed JSON ({exc.msg})") from None
    if not isinstance(out, dict):
        raise LLMError("the AI returned JSON that is not an object")
    return out


def chat_json(
    provider: Provider,
    *,
    model: str | None,
    api_key: str | None,
    system: str,
    user: str,
    ollama_url: str | None = None,
    temperature: float = 0.3,
) -> tuple[dict, dict]:
    """One chat completion that must return a JSON object. Returns (data, usage)."""
    if provider.secret and not api_key:
        raise LLMError(f"no {provider.label} API key stored (Settings → AI)")
    url = endpoint(provider, ollama_url)
    body = {
        "model": model or provider.default_model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    headers = {"Content-Type": "application/json", "User-Agent": "career-agent/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=provider.timeout_s) as resp:  # noqa: S310 - host allowlisted above
            raw = resp.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(8192) or b"{}")
            detail = detail.get("error", {}).get("message") if isinstance(detail.get("error"), dict) else detail
        except (ValueError, OSError):
            detail = ""
        hint = {401: "the API key was rejected", 403: "access denied", 404: "unknown model name",
                429: "free-tier rate limit reached; wait a minute"}.get(exc.code, "")  # fmt: skip
        raise LLMError(
            redact(f"{provider.label} HTTP {exc.code}: {hint or detail}"[:300]).replace(api_key or "\0", "***")
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        where = " (is Ollama running? start it with: ollama serve)" if provider.key == "ollama" else ""
        raise LLMError(
            redact(f"could not reach {provider.label}: {getattr(exc, 'reason', exc)}{where}")[:300]
        ) from None
    if len(raw) > MAX_RESPONSE:
        raise LLMError("the AI response was too large")
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError("unexpected response from the AI provider") from None
    return parse_json(content), payload.get("usage") or {}
