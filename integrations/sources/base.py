"""Connector contract, normalised posting model and a safe HTTP client shared by all job sources."""

import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; career-agent/0.1; personal job search)"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class SourceError(RuntimeError):
    pass


@dataclass
class JobPosting:
    """One posting exactly as a source describes it, lightly normalised. Nothing here is inferred."""

    source: str
    external_id: str
    title: str
    company: str
    url: str
    description: str  # plain text
    location: str | None = None
    location_restrictions: list[str] = field(default_factory=list)  # structured "who may apply" data
    remote_hint: str | None = None  # "remote" | "hybrid" | "onsite" when the source states it
    employment_type: str | None = None
    seniority_hint: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_text: str | None = None
    posted_at: datetime | None = None
    closes_at: date | None = None
    application_url: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class Connector(ABC):
    key: str
    hosts: tuple[str, ...]
    metered: bool = False  # True when requests count against a quota: never used for "widening" retries

    def __init__(self, http: "HttpClient", config: dict | None = None):
        self.http = http
        self.config = config or {}

    @abstractmethod
    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        """Return postings relevant to the queries (sources without search filter locally)."""


# ---------------------------------------------------------------- HTTP


class HttpClient:
    """GET-only client with a host allowlist, size cap, timeouts and per-host pacing (no redirects off-list)."""

    def __init__(
        self, allowed_hosts: set[str], min_interval_s: float = 1.0, timeout_s: float = 30, total_deadline_s: float = 90
    ):
        self.allowed = {h.lower() for h in allowed_hosts}
        self.min_interval = min_interval_s
        self.timeout = timeout_s  # per socket operation
        self.deadline = total_deadline_s  # whole response: stops servers that trickle bytes forever
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.requests = 0

    def _check(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in self.allowed:
            raise SourceError(f"blocked request to {parts.scheme}://{host} (not an allowed job-source host)")
        return host

    def _pace(self, host: str) -> None:
        with self._lock:
            wait = self._last.get(host, 0) + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def _get(self, url: str, accept: str, data: bytes | None = None) -> bytes:
        host = self._check(url)
        self._pace(host)
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310 - scheme/host checked
        opener = urllib.request.build_opener(_SafeRedirect(self))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                chunks: list[bytes] = []
                size, started = 0, time.monotonic()
                while chunk := resp.read(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        break
                    if time.monotonic() - started > self.deadline:
                        raise SourceError(f"{host} too slow: response not complete after {self.deadline:.0f}s")
                body = b"".join(chunks)
        except urllib.error.HTTPError as exc:
            raise SourceError(f"HTTP {exc.code} from {host}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SourceError(f"{host} unreachable: {getattr(exc, 'reason', exc)}") from exc
        finally:
            self.requests += 1
        if len(body) > MAX_RESPONSE_BYTES:
            raise SourceError(f"response from {host} larger than {MAX_RESPONSE_BYTES} bytes")
        return body

    def get_json(self, url: str):
        try:
            return json.loads(self._get(url, "application/json").decode("utf-8"))
        except ValueError as exc:
            raise SourceError(f"invalid JSON from {url}") from exc

    def post_json(self, url: str, payload: dict):
        """Only for APIs whose search is a POST (Jooble). Still subject to the host allowlist."""
        try:
            return json.loads(self._get(url, "application/json", json.dumps(payload).encode()).decode("utf-8"))
        except ValueError as exc:
            raise SourceError(f"invalid JSON from {url}") from exc

    def get_text(self, url: str) -> str:
        return self._get(url, "application/rss+xml, application/xml, text/xml").decode("utf-8", errors="replace")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, client: HttpClient):
        self.client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.client._check(newurl)  # a redirect may not leave the allowlist
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------- text helpers


class _Stripper(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    if "&lt;" in value[:500]:  # Greenhouse double-escapes its HTML
        value = html.unescape(value)
    parser = _Stripper()
    parser.feed(value)
    text = "".join(parser.out)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_datetime(value) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
            ts = float(value)
            return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts).astimezone()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def as_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def matches_any(text: str, queries: list[str]) -> bool:
    """Loose relevance filter for sources without server-side search: every word of some query appears."""
    low = text.lower()
    return any(all(w in low for w in q.lower().split()) for q in queries)
