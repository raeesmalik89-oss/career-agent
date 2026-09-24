import hashlib
import uuid
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agents.job_agent.agents import ingest_manual, run_job_scan
from agents.job_agent.extract import is_summary
from app.core import crypto
from app.db.enums import Actor, PkEligibility, RemoteType
from app.db.models import Job, JobRaw, JobSkill, JobSource, JobSourceLink, Secret, Skill, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.services import audit
from integrations.sources.base import JobPosting

router = APIRouter(tags=["jobs"])
SECRET_NAMES = {"jooble_api_key", "github_token", "smtp_password", "telegram_bot_token"}


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_keys: list[str] | None = Field(None, max_length=20)
    per_source_limit: int = Field(60, ge=1, le=300)


class ManualJobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=50, max_length=50_000)
    url: HttpUrl | None = None
    location: str | None = Field(None, max_length=300)
    remote: str | None = Field(None, pattern="^(remote|hybrid|onsite)$")
    salary_text: str | None = Field(None, max_length=200)
    # The full text of a job we already have (e.g. Jooble gave only a summary). It becomes that job's posting.
    job_id: uuid.UUID | None = None


# Job boards that resell or redirect postings. Their links often lead to sign-up walls or paid "resume upgrade"
# pages, so the dashboard asks the user to apply on the employer's own site instead.
AGGREGATOR_HOSTS = ("jooble.org", "jobleads.com", "whatjobs.com", "freehire.me", "talent.com", "adzuna.", "jobrapido.",
                    "careerjet.", "glassdoor.", "indeed.", "ziprecruiter.")  # fmt: skip


def is_aggregator(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(h in host for h in AGGREGATOR_HOSTS)


class EmployerLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl | None = None  # null clears it


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str = Field(min_length=4, max_length=500)


def _job_out(db: Session, job: Job, full: bool = False) -> dict:
    out = {
        "id": str(job.id),
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote_type": job.remote_type.value,
        "role_family": job.role_family,
        "seniority": job.seniority,
        "pk_eligibility": job.pk_eligibility.value,
        "pk_eligibility_evidence": job.pk_eligibility_evidence,
        "experience_required_years": float(job.experience_required_years) if job.experience_required_years else None,
        "salary": None
        if job.salary_min is None
        else {
            "min": float(job.salary_min),
            "max": float(job.salary_max) if job.salary_max else None,
            "currency": job.salary_currency,
            "source_text": job.salary_source_text,
        },
        "posted_date": job.posted_date.isoformat() if job.posted_date else None,
        "url": job.url,
        "application_url": job.application_url,
        "employer_url": job.employer_url,
        "aggregator_link": is_aggregator(job.application_url or job.url) and not job.employer_url,
        "content_version": job.content_version,
        "summary_only": is_summary(job.description),
        "first_seen_at": job.first_seen_at.isoformat(),
        "last_seen_at": job.last_seen_at.isoformat(),
    }
    if full:
        rows = db.execute(
            select(JobSkill, Skill.canonical_name, Skill.display_name)
            .outerjoin(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id == job.id)
        ).all()
        out["skills"] = [
            {"skill": key, "name": name or js.raw_text, "requirement": js.requirement.value, "weight": float(js.weight)}
            for js, key, name in rows
        ]
        links = db.execute(
            select(JobSourceLink, JobSource.key)
            .join(JobSource, JobSource.id == JobSourceLink.source_id)
            .where(JobSourceLink.job_id == job.id)
        ).all()
        out["sources"] = sorted({(key, link.url) for link, key in links})
        out["description"] = job.description
        out["education_required"] = job.education_required
        out["visa_requirement"] = job.visa_requirement
    return out


@router.post("/jobs/scan")
def scan(
    body: ScanIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:
    """Run discovery + extraction + dedup now (the scheduler runs it every morning from Milestone 10)."""
    result = run_job_scan(db, user.id, source_keys=body.source_keys, per_source_limit=body.per_source_limit)
    audit.record(
        db,
        action="jobs.scan",
        actor=Actor.user,
        user_id=user.id,
        entity_type="pipeline",
        entity_id=result["pipeline_run_id"],
        after=result["discovery"] | {"statuses": result["ingest"].get("statuses")},
        request_id=ctx.request_id,
    )
    db.commit()
    return result


@router.get("/jobs")
def list_jobs(
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
    family: str | None = Query(None, max_length=30),
    remote: RemoteType | None = None,
    pk: PkEligibility | None = None,
    q: str | None = Query(None, max_length=100),
    since: date | None = None,
    targets_only: bool = True,
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    stmt = select(Job)
    if targets_only:
        stmt = stmt.where(Job.role_family.is_not(None))
    if family:
        stmt = stmt.where(Job.role_family == family)
    if remote:
        stmt = stmt.where(Job.remote_type == remote)
    if pk:
        stmt = stmt.where(Job.pk_eligibility == pk)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company).like(like)))
    if since:
        stmt = stmt.where(Job.last_seen_at >= datetime.combine(since, datetime.min.time(), UTC))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    jobs = db.scalars(stmt.order_by(Job.last_seen_at.desc()).limit(limit))
    return {"total": total, "jobs": [_job_out(db, j) for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return _job_out(db, job, full=True)


@router.post("/jobs/manual", status_code=status.HTTP_201_CREATED)
def add_manual_job(
    body: ManualJobIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:
    """Paste a job you found yourself (LinkedIn, Rozee, a referral...), or the full text of a job we only have
    as a summary (pass job_id). It is analysed and scored like any other posting."""
    if body.job_id is not None and db.get(Job, body.job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    url = str(body.url) if body.url else ""
    ext = hashlib.sha256(f"{url}|{body.company}|{body.title}".encode()).hexdigest()[:32]
    posting = JobPosting(
        source="manual",
        external_id=ext,
        title=body.title,
        company=body.company,
        url=url,
        description=body.description,
        location=body.location,
        remote_hint=body.remote,
        salary_text=body.salary_text,
        posted_at=datetime.now(UTC),
        application_url=url or None,
    )
    result = ingest_manual(db, user.id, posting, job_id=body.job_id)
    job_id = next((ids[0] for ids in result["job_ids"].values() if ids), None)
    audit.record(
        db,
        action="jobs.manual_add",
        actor=Actor.user,
        user_id=user.id,
        entity_type="jobs",
        entity_id=job_id,
        after={
            "title": body.title,
            "company": body.company,
            "full_text_for": str(body.job_id) if body.job_id else None,
        },
        request_id=ctx.request_id,
    )
    db.commit()
    if job_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "could not analyse this posting")
    return get_job(uuid.UUID(job_id), user, db)


@router.get("/jobs-stats")
def stats(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "raw_postings_today": db.scalar(select(func.count(JobRaw.id)).where(JobRaw.fetched_at >= today)),
        "unique_jobs": db.scalar(select(func.count(Job.id))),
        "target_jobs": db.scalar(select(func.count(Job.id)).where(Job.role_family.is_not(None))),
        "by_family": dict(db.execute(select(Job.role_family, func.count()).group_by(Job.role_family)).all()),
        "by_pk_eligibility": {
            k.value: v
            for k, v in db.execute(
                select(Job.pk_eligibility, func.count())
                .where(Job.role_family.is_not(None))
                .group_by(Job.pk_eligibility)
            )
        },
    }


@router.put("/secrets", status_code=status.HTTP_204_NO_CONTENT)
def put_secret(
    body: SecretIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> None:
    """Store an API key encrypted (AES-256-GCM envelope). It is never returned by the API."""
    if body.name not in SECRET_NAMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"name must be one of {sorted(SECRET_NAMES)}")
    row = db.scalars(select(Secret).where(Secret.user_id == user.id, Secret.name == body.name)).first()
    from app.config import get_settings

    blob = crypto.encrypt(crypto.clean_secret(body.value), body.name.encode())
    if row is None:
        db.add(Secret(user_id=user.id, name=body.name, ciphertext=blob, key_version=get_settings().master_key_version))
    else:
        row.ciphertext, row.key_version = blob, get_settings().master_key_version
    audit.record(
        db,
        action="secret.put",
        actor=Actor.user,
        user_id=user.id,
        entity_type="secrets",
        entity_id=body.name,
        request_id=ctx.request_id,
    )
    db.commit()


@router.put("/jobs/{job_id}/employer-link")
def set_employer_link(
    job_id: uuid.UUID,
    body: EmployerLinkIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:
    """Save the employer's own posting/application page for a job (e.g. instead of a Jooble or JobLeads link)."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    url = str(body.url) if body.url else None
    if url and not url.startswith("https://"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "use the https:// link from the employer's site")
    if url and is_aggregator(url):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "that is a job-board link, not the employer's own site"
        )
    before = job.employer_url
    job.employer_url = url
    audit.record(db, action="jobs.employer_link", actor=Actor.user, user_id=user.id, entity_type="jobs",
                 entity_id=job.id, before={"employer_url": before}, after={"employer_url": url},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return _job_out(db, job, full=True)
