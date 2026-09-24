import hmac
import ipaddress
import logging
import re
import time
import uuid

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1 import (
    applications,
    auth,
    automation,
    dashboard,
    github,
    interview,
    jobs,
    matches,
    ops,
    resume,
    settings,
    skills,
    sources,
)
from app.config import get_settings
from app.core import checks
from app.core import logging as app_logging
from app.core.metrics import LATENCY, REQUESTS, health_registry
from app.db.session import get_db
from app.services.health import snapshot

access_log = logging.getLogger("app.access")
REQUEST_ID_RX = re.compile(r"[A-Za-z0-9._-]{1,64}")

# JSON API responses never need to load anything; /docs (development only) needs its CDN assets.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _loopback(request: Request) -> bool:
    try:
        return ipaddress.ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        return request.client is not None and request.client.host in ("localhost", "testclient")


def create_app() -> FastAPI:
    s = get_settings()
    checks.enforce(s)
    if s.app_env != "test":
        app_logging.configure("api")
    max_body = s.max_request_mb * 1024 * 1024
    app = FastAPI(
        title="Career Agent API",
        version="1.0.1",
        docs_url="/docs" if s.app_env != "production" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        # a client-supplied id is only accepted if it cannot forge log lines or headers
        request.state.request_id = rid if REQUEST_ID_RX.fullmatch(rid) else uuid.uuid4().hex
        token = app_logging.request_id_var.set(request.state.request_id)
        start = time.perf_counter()
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = max_body + 1
        try:
            if length > max_body:
                response: Response = JSONResponse(
                    {"detail": f"request larger than {s.max_request_mb} MB"}, status_code=413
                )
            else:
                response = await call_next(request)
        finally:
            app_logging.request_id_var.reset(token)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - start
        LATENCY.labels(request.method, path).observe(elapsed)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        if path not in ("/healthz", "/metrics"):
            # the route template, never the raw URL: paths and query strings can carry identifiers or tokens
            access_log.info(
                "%s %s %s", request.method, path, response.status_code,
                extra={"status": response.status_code, "duration_ms": round(elapsed * 1000, 1),
                       "request_id": request.state.request_id},
            )  # fmt: skip
        h = response.headers
        h["X-Request-ID"] = request.state.request_id
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        if not request.url.path.startswith(("/docs", "/openapi.json")):
            h.setdefault("Content-Security-Policy", API_CSP)
        if s.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        h.setdefault("Cache-Control", "no-store")
        return response

    for r in (
        auth.router,
        settings.router,
        sources.router,
        resume.router,
        github.router,
        jobs.router,
        matches.router,
        dashboard.router,
        applications.router,
        interview.router,
        skills.router,
        ops.router,
        automation.router,
    ):
        app.include_router(r, prefix="/api/v1")

    @app.get("/healthz", tags=["ops"])
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request, db: Session = Depends(get_db)):
        """Bearer METRICS_TOKEN if configured; otherwise loopback clients only."""
        if s.metrics_token:
            given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given.encode(), s.metrics_token.encode()):
                return JSONResponse({"detail": "metrics token required"}, status_code=401)
        elif not _loopback(request):
            return JSONResponse({"detail": "set METRICS_TOKEN to scrape from another host"}, status_code=403)
        body = generate_latest() + generate_latest(health_registry(snapshot(db)))
        return Response(body, media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
