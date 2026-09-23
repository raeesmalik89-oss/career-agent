"""Raw postings -> canonical jobs: normalisation, deduplication across sources, material-change detection."""

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.job_agent.extract import JobAnalysis, analyze, is_summary
from agents.taxonomy import Taxonomy
from app.db.enums import PkEligibility, RemoteType, Requirement
from app.db.models import Job, JobRaw, JobSkill, JobSource, JobSourceLink, Skill
from integrations.sources.base import JobPosting

_COMPANY_NOISE = r"\b(inc|incorporated|ltd|limited|llc|gmbh|pvt|private|corp|corporation|co|plc|sa|ag|bv|s\.a)\b\.?"
_TITLE_NOISE = r"\((m/w/d|f/m/d|m/f/d|w/m/d|all genders?|remote|hybrid|[^)]*\bremote\b[^)]*)\)|\b(100% )?remote\b"


def norm_company(name: str) -> str:
    s = re.sub(_COMPANY_NOISE, " ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def norm_title(title: str) -> str:
    s = re.sub(_TITLE_NOISE, " ", title.lower())
    s = re.split(r"\s[-–|]\s(?=[^-–|]*$)", s)[0] if re.search(r"\s[-–|]\s", s) and len(s) > 40 else s
    return re.sub(r"[^a-z0-9+#]+", " ", s).strip()


def fingerprint(company: str, title: str) -> str:
    return hashlib.sha256(f"{norm_company(company)}|{norm_title(title)}".encode()).hexdigest()


def _tokens(s: str) -> set[str]:
    return set(s.split())


def posting_payload(p: JobPosting) -> tuple[dict, str]:
    d = asdict(p)
    d["posted_at"] = p.posted_at.isoformat() if p.posted_at else None
    d["closes_at"] = p.closes_at.isoformat() if p.closes_at else None
    body = {k: v for k, v in d.items() if k != "raw"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return {"posting": body, "raw": d["raw"]}, digest


def material_signature(title: str, a: JobAnalysis) -> dict:
    """The fields whose change makes a job worth showing again."""
    return {
        "title": norm_title(title),
        "seniority": a.seniority,
        "remote_type": a.remote_type,
        "pk_eligibility": a.pk_eligibility,
        "salary": [a.salary_min, a.salary_max, a.salary_currency],
        "required_skills": sorted(s["skill"] for s in a.skills if s["requirement"] == "required"),
    }


def store_raw(db: Session, source: JobSource, p: JobPosting) -> tuple[JobRaw, bool]:
    """Keep every distinct version of a posting for audit. Returns (row, is_new_version)."""
    payload, digest = posting_payload(p)
    row = db.scalars(
        select(JobRaw).where(
            JobRaw.source_id == source.id, JobRaw.external_id == p.external_id[:300], JobRaw.payload_hash == digest
        )
    ).first()
    if row is not None:
        return row, False
    row = JobRaw(source_id=source.id, external_id=p.external_id[:300], payload=payload, payload_hash=digest)
    db.add(row)
    db.flush()
    return row, True


def find_existing(db: Session, p: JobPosting, fp: str, window_days: int = 45) -> Job | None:
    job = db.scalars(select(Job).where(Job.fingerprint == fp)).first()
    if job is not None:
        return job
    since = datetime.now(UTC) - timedelta(days=window_days)
    title_tokens = _tokens(norm_title(p.title))
    for cand in db.scalars(
        select(Job).where(Job.company_normalized == norm_company(p.company), Job.last_seen_at >= since)
    ):
        other = _tokens(norm_title(cand.title))
        if title_tokens and other and len(title_tokens & other) / len(title_tokens | other) >= 0.8:
            return cand
    return None


def upsert_job(
    db: Session,
    source: JobSource,
    raw: JobRaw,
    p: JobPosting,
    taxonomy: Taxonomy,
    skills: dict[str, Skill],
    target: Job | None = None,
) -> tuple[Job, str]:
    """Returns (job, status) where status is new | changed | unchanged | duplicate.

    `target` attaches the posting to a known job (the user pasted the full text of that job)."""
    a = analyze(p, taxonomy)
    fp = fingerprint(p.company, p.title)
    job = target or find_existing(db, p, fp)
    now = datetime.now(UTC)
    status = "new"
    if job is not None:
        linked = db.get(JobSourceLink, (job.id, raw.id)) is not None
        primary = _primary_posting(db, job)
        takes_over = primary is not None and _raw_is_summary(primary) and not is_summary(p.description)
        if takes_over:
            # The full posting replaces a summary: its requirements are now known, so the job is re-evaluated.
            job.content_version += 1
            status = "changed"
        elif primary is None or (primary.source_id, primary.external_id) != (source.id, raw.external_id):
            # Same vacancy on another board, or another location variant on the same board. Only the posting
            # that created the job may change it; the others add provenance and fill gaps.
            status = "duplicate"
        elif linked:
            status = "unchanged"  # this exact version of the primary posting was ingested before
        else:
            # A new version of the primary posting: compare with its previous version, not with job fields
            # (other variants may have enriched those, e.g. eligibility).
            previous = _previous_version(db, job, source, raw)
            before = (
                material_signature(previous.payload["posting"]["title"], analyze(_posting(previous), taxonomy))
                if previous is not None
                else None
            )
            if before != material_signature(p.title, a):
                job.content_version += 1
                status = "changed"
            else:
                status = "unchanged"
        job.last_seen_at = now
        if not linked:
            db.add(JobSourceLink(job_id=job.id, raw_id=raw.id, source_id=source.id, url=p.url[:1000]))
        if status in ("duplicate", "unchanged"):
            _fill_gaps(job, p, a)
            return job, status
    else:
        job = Job(fingerprint=fp, first_seen_at=now, last_seen_at=now, content_version=1)
        db.add(job)

    _apply(db, job, p, a, skills)
    if status == "changed" and primary is not None and primary.id != raw.id and _raw_is_summary(primary):
        # keep what only the summary's source knew (e.g. Jooble's country tag deciding eligibility)
        old = _posting(primary)
        _fill_gaps(job, old, analyze(old, taxonomy), bump=False)
    if status == "new":
        db.add(JobSourceLink(job_id=job.id, raw_id=raw.id, source_id=source.id, url=p.url[:1000]))
        db.flush()
    return job, status


def _apply(db: Session, job: Job, p: JobPosting, a: JobAnalysis, skills: dict[str, Skill]) -> None:
    """Write a posting's analysis onto the job (fields + skills)."""
    job.title, job.company = p.title[:300], p.company[:300] or "Unknown company"
    job.company_normalized = norm_company(p.company)[:300]
    job.location = (p.location or None) and p.location[:300]
    job.remote_type = RemoteType(a.remote_type)
    job.employment_type = (p.employment_type or None) and p.employment_type[:50]
    job.salary_min = Decimal(str(a.salary_min)) if a.salary_min else None
    job.salary_max = Decimal(str(a.salary_max)) if a.salary_max else None
    job.salary_currency = (a.salary_currency or None) and a.salary_currency[:3]
    job.salary_source_text = a.salary_text
    job.experience_required_years = Decimal(str(a.experience_years)) if a.experience_years is not None else None
    job.education_required = a.education
    job.visa_requirement = a.visa
    job.pk_eligibility = PkEligibility(a.pk_eligibility)
    job.pk_eligibility_evidence = a.pk_eligibility_evidence
    job.role_family, job.seniority = a.role_family, a.seniority
    job.posted_date = p.posted_at.date() if p.posted_at else None
    job.closing_date = p.closes_at
    job.url, job.application_url = p.url[:1000] or "about:blank", (p.application_url or p.url)[:1000]
    job.description = p.description or "(no description provided by the source)"
    job.description_hash = hashlib.sha256(job.description.encode()).hexdigest()
    db.flush()
    for js in db.scalars(select(JobSkill).where(JobSkill.job_id == job.id)):
        db.delete(js)
    for s in a.skills:
        db.add(
            JobSkill(
                job_id=job.id,
                skill_id=skills[s["skill"]].id if s["skill"] in skills else None,
                raw_text=s["raw"][:300],
                requirement=Requirement(s["requirement"]),
                weight=Decimal(str(s["weight"])),
            )
        )
    db.flush()


def reanalyze_jobs(db: Session, taxonomy: Taxonomy, skills: dict[str, Skill]) -> dict:
    """Re-run extraction on stored postings (no network). Used after extraction rules improve.

    A job whose eligibility, role family, seniority or remote type changes gets a new content_version,
    so it is re-evaluated (and, if it now qualifies, shown) like any materially changed posting.
    """
    counts = {"jobs": 0, "updated": 0}
    for job in list(db.scalars(select(Job))):
        primary = _primary_posting(db, job)
        if primary is None:
            continue
        counts["jobs"] += 1
        p = _posting(primary)
        a = analyze(p, taxonomy)
        before = (job.pk_eligibility.value, job.role_family, job.seniority, job.remote_type.value)
        _apply(db, job, p, a, skills)
        # variants on other boards/locations may still upgrade eligibility, exactly as during a scan
        for link in db.scalars(select(JobSourceLink).where(JobSourceLink.job_id == job.id)):
            if link.raw_id != primary.id:
                raw = db.get(JobRaw, link.raw_id)
                variant = _posting(raw)
                _fill_gaps(job, variant, analyze(variant, taxonomy), bump=False)
        if (job.pk_eligibility.value, job.role_family, job.seniority, job.remote_type.value) != before:
            job.content_version += 1
            counts["updated"] += 1
    db.flush()
    return counts


def _posting(raw: JobRaw) -> JobPosting:
    from agents.job_agent.agents import posting_from_payload

    return posting_from_payload(raw.payload)


def _previous_version(db: Session, job: Job, source: JobSource, raw: JobRaw) -> JobRaw | None:
    return db.scalars(
        select(JobRaw)
        .join(JobSourceLink, JobSourceLink.raw_id == JobRaw.id)
        .where(
            JobSourceLink.job_id == job.id,
            JobRaw.source_id == source.id,
            JobRaw.external_id == raw.external_id,
            JobRaw.id != raw.id,
        )
        .order_by(JobRaw.fetched_at.desc())
        .limit(1)
    ).first()


def _primary_posting(db: Session, job: Job) -> JobRaw | None:
    """The posting that owns the job's fields: the earliest full-text one, else the earliest summary.

    A summary (e.g. Jooble's ~280-character teaser) hides requirements such as years of experience, so a full
    copy of the same vacancy from any board, or pasted by the user, takes over as soon as it exists."""
    raws = db.scalars(
        select(JobRaw)
        .join(JobSourceLink, JobSourceLink.raw_id == JobRaw.id)
        .where(JobSourceLink.job_id == job.id)
        .order_by(JobRaw.fetched_at, JobRaw.id)
    ).all()
    return next((r for r in raws if not _raw_is_summary(r)), raws[0] if raws else None)


def _raw_is_summary(raw: JobRaw) -> bool:
    return is_summary((raw.payload.get("posting") or {}).get("description"))


def _fill_gaps(job: Job, p: JobPosting, a: JobAnalysis, bump: bool = True) -> None:
    """A duplicate from another board may carry facts the first source lacked (e.g. salary)."""
    if job.salary_min is None and a.salary_min:
        job.salary_min, job.salary_max = Decimal(str(a.salary_min)), Decimal(str(a.salary_max or a.salary_min))
        job.salary_currency, job.salary_source_text = a.salary_currency, a.salary_text
    upgrade = job.pk_eligibility == PkEligibility.unknown and a.pk_eligibility != "unknown"
    if upgrade or (job.pk_eligibility == PkEligibility.ineligible and a.pk_eligibility == "eligible"):
        # If any variant of the vacancy is open to Pakistan, the job is.
        job.pk_eligibility = PkEligibility(a.pk_eligibility)
        job.pk_eligibility_evidence = f"{a.pk_eligibility_evidence} (from {p.source})"
        if bump:
            job.content_version += 1  # eligibility is material: the job may now be shown (or hidden)
