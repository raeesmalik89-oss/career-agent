"""Idempotent seed of the job-source registry.

read_allowed reflects the source's published access method (public API/RSS/feed).
auto_apply_allowed always starts False: it is enabled per source by the owner after a ToS review.
Platforms whose terms prohibit automation are marked auto_apply_forbidden and are only reachable
through their job-alert emails or manual paste.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import SourceKind
from app.db.models import JobSource

SOURCES: list[dict] = [
    dict(
        key="remoteok",
        name="RemoteOK",
        kind=SourceKind.api,
        base_url="https://remoteok.com/api",
        read_allowed=True,
        tos_url="https://remoteok.com/legal",
        tos_notes="Public JSON API; must link back to RemoteOK and credit it as the source.",
        rate_limit_per_min=2,
    ),
    dict(
        key="weworkremotely",
        name="We Work Remotely",
        kind=SourceKind.rss,
        base_url="https://weworkremotely.com/remote-jobs.rss",
        read_allowed=True,
        tos_url="https://weworkremotely.com/terms-of-service",
        tos_notes="Public RSS feeds per category.",
        rate_limit_per_min=2,
    ),
    dict(
        key="remotive",
        name="Remotive",
        kind=SourceKind.api,
        base_url="https://remotive.com/api/remote-jobs",
        read_allowed=True,
        tos_url="https://remotive.com/terms-of-service",
        tos_notes="Public API; link back to Remotive; max ~4 requests/day recommended.",
        rate_limit_per_min=1,
    ),
    dict(
        key="himalayas",
        name="Himalayas",
        kind=SourceKind.api,
        base_url="https://himalayas.app/jobs/api",
        read_allowed=True,
        tos_url="https://himalayas.app/terms",
        tos_notes="Public jobs API with attribution.",
        rate_limit_per_min=2,
    ),
    dict(
        key="arbeitnow",
        name="Arbeitnow",
        kind=SourceKind.api,
        base_url="https://www.arbeitnow.com/api/job-board-api",
        read_allowed=True,
        tos_url="https://www.arbeitnow.com/terms",
        rate_limit_per_min=2,
    ),
    dict(
        key="jooble",
        name="Jooble",
        kind=SourceKind.api,
        base_url="https://jooble.org/api/",
        read_allowed=True,
        tos_url="https://jooble.org/api/about",
        tos_notes="Free API key required (stored encrypted as secret 'jooble_api_key'). Covers Pakistan.",
        rate_limit_per_min=5,
    ),
    dict(
        key="greenhouse",
        name="Greenhouse job boards",
        kind=SourceKind.ats_board,
        base_url="https://boards-api.greenhouse.io/v1/boards/",
        read_allowed=True,
        tos_notes="Public read-only board API per company token (config.companies).",
        rate_limit_per_min=10,
        config={"companies": []},
    ),
    dict(
        key="lever",
        name="Lever postings",
        kind=SourceKind.ats_board,
        base_url="https://api.lever.co/v0/postings/",
        read_allowed=True,
        tos_notes="Public read-only postings API per company (config.companies).",
        rate_limit_per_min=10,
        config={"companies": []},
    ),
    dict(
        key="ashby",
        name="Ashby job boards",
        kind=SourceKind.ats_board,
        base_url="https://api.ashbyhq.com/posting-api/job-board/",
        read_allowed=True,
        tos_notes="Public read-only posting API per company (config.companies).",
        rate_limit_per_min=10,
        config={"companies": []},
    ),
    dict(
        key="manual",
        name="Manual paste (URL / JD text)",
        kind=SourceKind.manual,
        read_allowed=True,
        tos_notes="Jobs you paste yourself.",
        rate_limit_per_min=60,
        enabled=True,
    ),
    dict(
        key="linkedin_alerts",
        name="LinkedIn job-alert emails",
        kind=SourceKind.email_import,
        read_allowed=True,
        tos_url="https://www.linkedin.com/legal/user-agreement",
        tos_notes="LinkedIn prohibits scraping/automation. Only alert emails in your own inbox are parsed; "
        "applications are always manual.",
        config={"auto_apply_forbidden": True},
    ),
    dict(
        key="indeed_alerts",
        name="Indeed job-alert emails",
        kind=SourceKind.email_import,
        read_allowed=True,
        tos_url="https://www.indeed.com/legal",
        tos_notes="No automation of Indeed; alert emails only.",
        config={"auto_apply_forbidden": True},
    ),
    dict(
        key="glassdoor_alerts",
        name="Glassdoor job-alert emails",
        kind=SourceKind.email_import,
        read_allowed=True,
        tos_notes="No automation of Glassdoor; alert emails only.",
        config={"auto_apply_forbidden": True},
    ),
    dict(
        key="rozee_alerts",
        name="Rozee.pk job-alert emails",
        kind=SourceKind.email_import,
        read_allowed=True,
        tos_url="https://www.rozee.pk/terms-of-use",
        tos_notes="No public API; alert emails/manual paste only.",
        config={"auto_apply_forbidden": True},
    ),
    dict(
        key="mustakbil_alerts",
        name="Mustakbil job-alert emails",
        kind=SourceKind.email_import,
        read_allowed=True,
        tos_notes="No public API; alert emails/manual paste only.",
        config={"auto_apply_forbidden": True},
    ),
]


def seed_sources(db: Session) -> int:
    """Insert missing sources; never overwrites owner decisions (enabled / auto_apply / tos review)."""
    existing = set(db.scalars(select(JobSource.key)))
    added = 0
    for spec in SOURCES:
        if spec["key"] not in existing:
            db.add(JobSource(**spec))
            added += 1
    return added
