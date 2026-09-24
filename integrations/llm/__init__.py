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
        "groq", "Groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "groq_api_key", 90,
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

# Providers retire models; when the configured one is gone, the first available of these is used instead.
PREFERRED = {
    "groq": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
    "ollama": ["llama3.2:3b", "qwen2.5:3b", "phi3:mini"],
}
NOT_CHAT = ("whisper", "guard", "orpheus", "tts", "embed", "embedding", "imagen", "veo", "aqa", "vision-only")

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


def _request(url: str, provider: Provider, api_key: str | None, body: dict | None) -> bytes:
    headers = {"Content-Type": "application/json", "User-Agent": "career-agent/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=provider.timeout_s) as resp:  # noqa: S310 - host allowlisted
            raw = resp.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read(8192) or b"{}")
            err = err[0] if isinstance(err, list) and err else err
            e = err.get("error") if isinstance(err, dict) else None
            detail = (e.get("message") or "") if isinstance(e, dict) else str(e or "")
            code = (e.get("code") or e.get("status") or "") if isinstance(e, dict) else ""
        except (ValueError, OSError, AttributeError):
            detail, code = "", ""
        hint = {401: "the API key was rejected: store a new one", 403: "this key has no access",
                429: "free-tier rate limit reached; wait a minute and try again"}.get(exc.code, "")  # fmt: skip
        text = f"{provider.label} HTTP {exc.code}: {'; '.join(x for x in (hint, detail) if x)}"[:400]
        raise ProviderHTTPError(
            redact(text).replace(api_key, "***") if api_key else redact(text), exc.code, str(code)
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        where = " (is Ollama running? start it with: ollama serve)" if provider.key == "ollama" else ""
        raise LLMError(
            redact(f"could not reach {provider.label}: {getattr(exc, 'reason', exc)}{where}")[:300]
        ) from None
    if len(raw) > MAX_RESPONSE:
        raise LLMError("the AI response was too large")
    return raw


class ProviderHTTPError(LLMError):
    def __init__(self, message: str, status: int, code: str):
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def model_missing(self) -> bool:
        return self.status == 404 or "model" in self.code.lower() and "not" in self.code.lower()


def list_models(provider: Provider, api_key: str | None, ollama_url: str | None = None) -> list[str]:
    """Chat models this key can use (OpenAI-compatible GET /models), best-known first."""
    url = endpoint(provider, ollama_url).removesuffix("/chat/completions") + "/models"
    try:
        payload = json.loads(_request(url, provider, api_key, None))
    except ValueError:
        raise LLMError(f"{provider.label} returned an unreadable model list") from None
    ids = []
    for m in payload.get("data", []):
        mid = str(m.get("id", "")).removeprefix("models/")
        if mid and m.get("active", True) is not False and not any(t in mid.lower() for t in NOT_CHAT):
            ids.append(mid)
    pref = PREFERRED.get(provider.key, [])
    return sorted(set(ids), key=lambda i: (pref.index(i) if i in pref else len(pref), i))


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
    chosen = model or provider.default_model

    def call(m: str) -> bytes:
        body = {
            "model": m,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            # some providers (Groq) require the word "json" in the prompt when JSON output is requested
            "messages": [
                {"role": "system", "content": system + "\n\nRespond with a single JSON object only."},
                {"role": "user", "content": user},
            ],
        }
        return _request(url, provider, api_key, body)

    try:
        raw = call(chosen)
    except ProviderHTTPError as exc:
        if not exc.model_missing:
            raise
        # the model was retired or renamed: use the best one the provider still offers, once
        available = [m for m in list_models(provider, api_key, ollama_url) if m != chosen]
        if not available:
            raise LLMError(f"{exc} (and no other model is available for this key)") from None
        chosen = available[0]
        raw = call(chosen)
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError("unexpected response from the AI provider") from None
    usage = dict(payload.get("usage") or {})
    usage["model"] = chosen
    return parse_json(content), usage
