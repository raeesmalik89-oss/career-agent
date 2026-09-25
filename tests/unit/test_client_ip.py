"""The visitor IP used for rate limits: Cloudflare's header is only trusted from the local proxy."""

from starlette.requests import Request

from app.deps import client_ip


def _req(peer: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "client": (peer, 5000), "headers": raw})


def test_cloudflare_ip_used_behind_local_proxy():
    assert client_ip(_req("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"})) == "203.0.113.9"
    assert client_ip(_req("::1", {"CF-Connecting-IP": "2001:db8::7"})) == "2001:db8::7"


def test_header_ignored_from_other_peers_and_when_invalid():
    assert client_ip(_req("198.51.100.4", {"CF-Connecting-IP": "203.0.113.9"})) == "198.51.100.4"
    assert client_ip(_req("127.0.0.1", {"CF-Connecting-IP": "not-an-ip"})) == "127.0.0.1"
    assert client_ip(_req("127.0.0.1")) == "127.0.0.1"
