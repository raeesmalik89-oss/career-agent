"""Job Discovery + Job Ingest (extraction and deduplication) agents and the scan pipeline that runs them."""

import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from agents.base import Agent, AgentContext
from agents.job_agent.ingest import store_raw, upsert_job
from agents.resume_agent.agent import sync_taxonomy
from agents.taxonomy import Taxonomy, get_taxonomy
from app.core import crypto
from app.db.enums import Confidence
from app.db.models import JobRaw, JobSource, Secret
from app.services import settings_service
from integrations.sources.base import Connector, HttpClient, JobPosting, SourceError
from integrations.sources.connectors import CONNECTORS

FAMILY_QUERIES: dict[str, list[str]] = {
    "devops": ["devops engineer", "devops"],
    "sre": ["site reliability engineer", "sre"],
    "aiops": ["aiops"],
    "ai_engineer": ["ai engineer", "machine learning engineer", "llm engineer"],
    "mlops": ["mlops", "ml platform"],
    "cloud": ["cloud engineer", "cloud infrastructure"],
    "platform": ["platform engineer"],
    "devsecops": ["devsecops", "cloud security engineer"],
    "kubernetes": ["kubernetes"],
    "ai_platform": ["ai platform", "ai infrastructure"],
    "cloud_ai_infra": ["ai infrastructure"],
    "sre_ai": ["site reliability"],
}
WIDER_QUERIES = [
    "infrastructure engineer",
    "systems engineer",
    "automation engineer",
    "observability",
    "linux",
    "terraform",
    "python engineer",
]
MAX_AGE_DAYS = 45


def build_queries(families: list[str]) -> list[str]:
    out: list[str] = []
    for f in families:
        for q in FAMILY_QUERIES.get(f, []):
            if q not in out:
                out.append(q)
    return out


def _secret(db, user_id: uuid.UUID, name: str) -> str | None:
    row = db.scalars(select(Secret).where(Secret.user_id == user_id, Secret.name == name)).first()
    return crypto.clean_secret(crypto.decrypt(row.ciphertext, name.encode())) if row else None


def make_connector(src: JobSource, http: HttpClient, db, user_id: uuid.UUID) -> Connector:
    config = dict(src.config or {})
    if src.key == "jooble":
        config["api_key"] = _secret(db, user_id, "jooble_api_key")
    return CONNECTORS[src.key](http, config)


# ---------------------------------------------------------------- discovery


class DiscoveryInput(BaseModel):
    user_id: uuid.UUID
    source_keys: list[str] | None = None  # default: every enabled source with a connector
    queries: list[str] | None = None  # default: from settings.target_role_families
    per_source_limit: int = Field(60, ge=1, le=500)
    min_scanned: int | None = None  # default: settings.daily_min_jobs_scanned


class JobDiscoveryAgent(Agent[DiscoveryInput]):
    name = "job_discovery"

    def __init__(self, http: HttpClient | None = None):
        self._http = http

    def summarize_input(self, payload: DiscoveryInput) -> str:
        return f"sources={payload.source_keys or 'enabled'}; limit={payload.per_source_limit}"

    def execute(self, payload: DiscoveryInput, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        db = ctx.db
        prefs, _ = settings_service.get_effective(db, payload.user_id)
        queries = payload.queries or build_queries(prefs.preferences.target_role_families)
        min_scanned = payload.min_scanned or prefs.preferences.daily_min_jobs_scanned
        q = select(JobSource).where(JobSource.read_allowed.is_(True))
        q = (
            q.where(JobSource.key.in_(payload.source_keys))
            if payload.source_keys
            else q.where(JobSource.enabled.is_(True))
        )
        sources = [s for s in db.scalars(q) if s.key in CONNECTORS]
        http = self._http or HttpClient({h for s in sources for h in CONNECTORS[s.key].hosts})
        cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)

        raw_ids: list[str] = []
        per_source: Counter = Counter()
        stale = 0

        def run(query_set: list[str]) -> None:
            nonlocal stale
            connectors = {src.key: make_connector(src, http, db, payload.user_id) for src in sources}

            def fetch(key: str) -> tuple[str, list[JobPosting] | SourceError]:
                try:
                    return key, connectors[key].fetch(query_set, payload.per_source_limit)
                except SourceError as exc:
                    return key, exc

            # Sources are different hosts, so they are fetched in parallel; DB writes stay on this thread.
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = dict(pool.map(fetch, connectors))
            for src in sources:
                used = getattr(connectors[src.key], "requests_made", 0)
                if used:  # metered sources (Jooble) keep a running count of their request quota
                    src.config = {
                        **(src.config or {}),
                        "requests_used": int((src.config or {}).get("requests_used", 0)) + used,
                    }
                postings = results[src.key]
                if isinstance(postings, SourceError):
                    ctx.error("source_failed", f"{src.key}: {postings}", retryable=True)
                    continue
                for p in postings:
                    if p.posted_at and p.posted_at.astimezone(UTC) < cutoff:
                        stale += 1
                        continue
                    row, new_version = store_raw(db, src, p)
                    if str(row.id) not in raw_ids:
                        raw_ids.append(str(row.id))
                        per_source[src.key] += 1
                ctx.act("fetched", target=src.key, postings=len(postings), queries=len(query_set))

        run(queries)
        widened = False
        if len(raw_ids) < min_scanned:  # keep scanning wider until the daily minimum is met (never inflate scores)
            widened = True
            run([w for w in WIDER_QUERIES if w not in queries])
        output = {
            "scanned": len(raw_ids),
            "min_scanned": min_scanned,
            "met_minimum": len(raw_ids) >= min_scanned,
            "widened": widened,
            "per_source": dict(per_source),
            "skipped_stale": stale,
            "queries": queries,
            "raw_ids": raw_ids,
            "http_requests": http.requests,
        }
        if not output["met_minimum"]:
            ctx.act(
                "warning",
                target="below_minimum",
                scanned=len(raw_ids),
                target_min=min_scanned,
                hint="enable more sources, add company boards, or add a Jooble API key",
            )
        return output, Confidence.high if not ctx.errors else Confidence.medium


# ---------------------------------------------------------------- ingest (extraction + dedup)


class IngestInput(BaseModel):
    raw_ids: list[str]


class JobIngestAgent(Agent[IngestInput]):
    """Extracts structured facts from each raw posting and merges it into a canonical job."""

    name = "job_ingest"

    def __init__(self, taxonomy: Taxonomy | None = None):
        self.taxonomy = taxonomy or get_taxonomy()

    def summarize_input(self, payload: IngestInput) -> str:
        return f"{len(payload.raw_ids)} raw postings"

    def execute(self, payload: IngestInput, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        db = ctx.db
        skills = sync_taxonomy(db, self.taxonomy)
        statuses: Counter = Counter()
        families: Counter = Counter()
        eligibility: Counter = Counter()
        job_ids: dict[str, list[str]] = {"new": [], "changed": [], "unchanged": [], "duplicate": []}
        for rid in payload.raw_ids:
            raw = db.get(JobRaw, uuid.UUID(rid))
            if raw is None:
                continue
            src = db.get(JobSource, raw.source_id)
            p = posting_from_payload(raw.payload)
            try:
                job, status = upsert_job(db, src, raw, p, self.taxonomy, skills)
            except Exception as exc:  # noqa: BLE001 - one malformed posting must not stop the batch
                ctx.error("ingest_failed", f"{src.key}:{raw.external_id}: {type(exc).__name__}: {exc}")
                continue
            statuses[status] += 1
            families[job.role_family or "not_target"] += 1
            eligibility[job.pk_eligibility.value] += 1
            if str(job.id) not in job_ids[status]:
                job_ids[status].append(str(job.id))
        output = {
            "statuses": dict(statuses),
            "unique_jobs": len({j for ids in job_ids.values() for j in ids}),
            "role_families": dict(families),
            "pk_eligibility": dict(eligibility),
            "job_ids": job_ids,
        }
        return output, Confidence.high if not ctx.errors else Confidence.medium


def posting_from_payload(payload: dict) -> JobPosting:
    d = dict(payload["posting"])
    from integrations.sources.base import parse_datetime

    d["posted_at"] = parse_datetime(d.get("posted_at"))
    d["closes_at"] = None
    return JobPosting(**d, raw=payload.get("raw") or {})


# ---------------------------------------------------------------- pipeline


def run_job_scan(
    db,
    user_id: uuid.UUID,
    *,
    source_keys: list[str] | None = None,
    http: HttpClient | None = None,
    per_source_limit: int = 60,
) -> dict:
    """morning_scan steps 1-3: discover -> store raw -> extract + dedup. Matching comes in Milestone 5."""
    pipeline = uuid.uuid4()
    disc = JobDiscoveryAgent(http).run(
        DiscoveryInput(user_id=user_id, source_keys=source_keys, per_source_limit=per_source_limit),
        db,
        user_id=user_id,
        pipeline_run_id=pipeline,
    )
    ingest = JobIngestAgent().run(
        IngestInput(raw_ids=disc.output.get("raw_ids", [])), db, user_id=user_id, pipeline_run_id=pipeline
    )
    return {
        "pipeline_run_id": str(pipeline),
        "discovery": {k: v for k, v in disc.output.items() if k != "raw_ids"},
        "ingest": ingest.output,
        "errors": [e.model_dump() for e in (*disc.errors, *ingest.errors)],
    }


def ingest_manual(db, user_id: uuid.UUID, posting: JobPosting) -> dict:
    """A job the user pasted: stored and analysed exactly like a fetched posting."""
    src = db.scalars(select(JobSource).where(JobSource.key == "manual")).one()
    raw, _ = store_raw(db, src, posting)
    return JobIngestAgent().run(IngestInput(raw_ids=[str(raw.id)]), db, user_id=user_id).output
