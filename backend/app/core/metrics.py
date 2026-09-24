"""Prometheus metrics: HTTP traffic (in-process) plus business/health gauges computed from the database at scrape
time, so they are correct whichever process (API or scheduler) did the work."""

from datetime import datetime

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["method", "route"])
AUTH_EVENTS = Counter("career_auth_events_total", "Authentication events", ["event"])
RATE_LIMITED = Counter("career_rate_limited_total", "Requests refused by a rate limit", ["limit"])

PIPELINE_STATUS = {"succeeded": 1, "partial": 0.5, "running": 0.5, "failed": 0}


def _ts(dt: datetime | None) -> float:
    return dt.timestamp() if dt else 0


def health_registry(snap: dict) -> CollectorRegistry:
    """A fresh registry per scrape (values come from the snapshot, not from counters in this process)."""
    reg = CollectorRegistry()
    gauges: dict[str, Gauge] = {}

    def gauge(name: str, doc: str, value: float | None, **labels: str) -> None:
        """Unknown values (e.g. never ran) are exported as -1."""
        if name not in gauges:
            gauges[name] = Gauge(name, doc, list(labels), registry=reg)
        g = gauges[name]
        (g.labels(**labels) if labels else g).set(float(value if value is not None else -1))

    gauge("career_health_status", "0 ok, 1 warnings, 2 failing", {"ok": 0, "warn": 1, "fail": 2}[snap["status"]])
    gauge("career_database_latency_ms", "SELECT 1 round trip", snap["database"]["latency_ms"])
    m = snap["database"]["migration"]
    gauge("career_migrations_pending", "1 if the database is behind the code", 0 if m["current"] == m["head"] else 1)
    gauge("career_scheduler_up", "1 if the scheduler heartbeat is fresh", 1 if snap["scheduler"]["running"] else 0)
    gauge("career_scheduler_heartbeat_age_seconds", "seconds since the last tick", snap["scheduler"]["age_seconds"])
    for name, p in snap["pipelines"].items():
        gauge("career_pipeline_last_status", "1 ok, 0.5 partial/running, 0 failed", PIPELINE_STATUS.get(p["status"], 0),
              pipeline=name)  # fmt: skip
        gauge("career_pipeline_last_success_timestamp_seconds", "unix time of the last success",
              _ts(p["last_success"]), pipeline=name)  # fmt: skip
    gauge("career_jobs_last_fetch_age_seconds", "seconds since a posting was last fetched", snap["jobs"]["age_seconds"])
    gauge("career_agent_runs_failed_24h", "failed agent runs in the last 24 h", snap["agent_runs_failed_24h"])
    gauge(
        "career_notifications_failed_3d", "failed email/Telegram deliveries (3 days)", snap["notifications_failed_3d"]
    )
    if snap["jooble_quota"]:
        q = snap["jooble_quota"]
        gauge("career_jooble_quota_remaining", "Jooble requests left", q["total"] - q["used"])
    if snap["backup"]["applies"]:
        gauge("career_backup_age_seconds", "seconds since the newest backup", snap["backup"]["age_seconds"])
    gauge("career_disk_free_bytes", "free space for storage/", snap["disk_free_bytes"])
    return reg
