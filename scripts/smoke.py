"""Post-deployment smoke test. Read-only: it never logs in and never changes anything.

    python scripts/smoke.py https://careers.example.com     (a server behind Caddy)
    python scripts/smoke.py http://localhost:3000            (local dashboard)

Exit code 0 when every check passes."""

import sys
import urllib.error
import urllib.request

CHECKS: list[tuple[str, bool, str]] = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


def fetch(url: str, follow: bool = True) -> tuple[int, dict[str, str], str]:
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "career-agent-smoke/1.0"})  # noqa: S310
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(20_000).decode("utf-8", "replace")


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail and not ok else ''}")


def main(base: str) -> int:
    base = base.rstrip("/")
    print(f"Smoke test for {base}")
    status, headers, body = fetch(f"{base}/login")
    check("dashboard login page loads", status == 200, f"HTTP {status}")
    check("dashboard sends a Content-Security-Policy", "content-security-policy" in headers)
    check("dashboard forbids framing", headers.get("x-frame-options", "").upper() == "DENY")
    check("no framework banner", "x-powered-by" not in headers)

    status, headers, body = fetch(f"{base}/api/v1/auth/me")
    check("API reachable through the dashboard and protected", status == 401, f"HTTP {status}")
    check("API responses carry a request id", "x-request-id" in headers)
    check("API responses are not cached", "no-store" in headers.get("cache-control", ""))

    status, _, _ = fetch(f"{base}/metrics")
    check("/metrics is not exposed publicly", status in (401, 403, 404), f"HTTP {status}")
    status, _, _ = fetch(f"{base}/api/v1/pipelines")
    check("automation API needs a login", status == 401, f"HTTP {status}")

    if base.startswith("https://"):
        _, headers, _ = fetch(f"{base}/login")
        check("HSTS enabled", "max-age=" in headers.get("strict-transport-security", ""))
        status, headers, _ = fetch("http://" + base.removeprefix("https://") + "/login", follow=False)
        check("plain HTTP redirects to HTTPS", status in (301, 302, 307, 308)
              and headers.get("location", "").startswith("https://"), f"HTTP {status}")  # fmt: skip

    failed = [c for c in CHECKS if not c[1]]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("usage: python scripts/smoke.py <https://your-domain | http://localhost:3000>")
    sys.exit(main(sys.argv[1]))
