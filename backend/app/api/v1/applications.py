import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.application_agent import service
from agents.application_agent.ai_tailor import AiTailorError, ai_config, tailor
from agents.application_agent.docx_render import safe_filename
from agents.application_agent.service import ApplicationError
from agents.job_agent.agents import ingest_manual
from app.api.v1.jobs import _job_out
from app.db.enums import Actor, ApplicationStatus
from app.db.models import Application, ApplicationAnswer, ApplicationEvent, Job, JobMatch, ResumeVersion, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, rate_limit, request_ctx
from app.services import audit, storage

router = APIRouter(tags=["applications"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(max_length=10_000)


class TailorIn(BaseModel):
    """A job you found anywhere: paste it and get a tailored package (AI-rewritten when AI is on)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=100, max_length=50_000)
    url: HttpUrl | None = None
    use_ai: bool = True


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=500)


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    note: str | None = Field(None, max_length=500)


def _own(db: Session, user: User, app_id: uuid.UUID) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    return app


def _raise(e: ApplicationError):
    if e.existing_id:
        return JSONResponse(status_code=e.status_code, content={"detail": str(e), "existing_id": str(e.existing_id)})
    raise HTTPException(e.status_code, str(e))


def _summary(db: Session, app: Application, job: Job) -> dict:
    match = db.get(JobMatch, app.match_id) if app.match_id else None
    return {
        "id": str(app.id),
        "status": app.status.value,
        "mode": app.mode.value,
        "job": {"id": str(job.id), "title": job.title, "company": job.company, "location": job.location},
        "score": float(match.estimated_fit_score) if match else None,
        "confidence": match.score_confidence.value if match else None,
        "created_at": app.created_at.isoformat(),
        "last_update": app.last_update.isoformat(),
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
    }


def _detail(db: Session, app: Application) -> dict:
    job = db.get(Job, app.job_id)
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    answers = db.scalars(
        select(ApplicationAnswer)
        .where(ApplicationAnswer.application_id == app.id)
        .order_by(ApplicationAnswer.created_at)
    ).all()
    events = db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.at)
    ).all()
    return _summary(db, app, job) | {
        "job_detail": _job_out(db, job),
        # the employer's own page wins, even if it was added after the package was prepared
        "application_url": job.employer_url or app.application_url,
        "resume": rv.parsed.get("resume") if rv else None,
        "resume_filename": rv.original_filename if rv else None,
        "resume_validation": app.policy_decision.get("resume_validation"),
        "ai": app.policy_decision.get("ai"),
        "policy": {k: app.policy_decision.get(k) for k in ("prepare", "submission")},
        "blockers": service._blockers(db, app) if app.status in service.PRE_SUBMIT else [],
        "answers": [
            {
                "id": str(a.id),
                "question": a.question,
                "answer": a.answer,
                "category": a.category.value,
                "validation_status": a.validation_status.value,
                "validation_notes": a.validation_notes,
                "cited_fact_ids": a.cited_fact_ids,
                "approved": a.approved_by_user_at is not None,
                "ai": bool(app.policy_decision.get("answers_meta", {}).get(str(a.id), {}).get("ai")),
            }
            for a in answers
        ],
        "events": [
            {"type": e.event_type, "actor": e.actor.value, "at": e.at.isoformat(), "detail": e.detail} for e in events
        ],
        "next_statuses": sorted(s.value for s in service.TRANSITIONS.get(app.status, set())),
    }


def _audit(db, user, ctx, action, app, **after):
    audit.record(db, action=action, actor=Actor.user, user_id=user.id, entity_type="applications",
                 entity_id=app.id, after=after or None, request_id=ctx.request_id)  # fmt: skip


@router.get("/applications")
def list_applications(user: User = Depends(any_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(Application.user_id == user.id)
        .order_by(Application.last_update.desc())
    ).all()
    return [_summary(db, a, j) for a, j in rows]


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def prepare(body: PrepareIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
            ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    """Build a tailored package for a job. Nothing is sent anywhere: it waits in your approval queue."""
    try:
        app = service.prepare(db, user.id, body.job_id)
    except ApplicationError as e:
        db.rollback()
        return _raise(e)
    _audit(db, user, ctx, "application.prepare", app, job_id=str(body.job_id))
    db.commit()
    return _detail(db, app)


@router.get("/applications/{app_id}")
def get_application(app_id: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    app = _own(db, user, app_id)
    if app.status in service.PRE_SUBMIT and user.role.value == "owner":
        service.revalidate(db, app)  # facts may have been verified or edited since
        db.commit()
    return _detail(db, app)


@router.patch("/applications/{app_id}/answers/{answer_id}")
def edit_answer(app_id: uuid.UUID, answer_id: uuid.UUID, body: AnswerIn, user: User = Depends(owner_only),
                db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    app = _own(db, user, app_id)
    try:
        service.edit_answer(db, app, answer_id, body.answer)
    except ApplicationError as e:
        return _raise(e)
    _audit(db, user, ctx, "application.answer_edit", app, answer_id=str(answer_id))
    db.commit()
    return _detail(db, app)


@router.post("/applications/{app_id}/rebuild")
def rebuild(app_id: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db),
            ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    """Regenerate the package from your current facts (your answer edits are replaced)."""
    app = _own(db, user, app_id)
    try:
        service.rebuild(db, app)
    except ApplicationError as e:
        return _raise(e)
    _audit(db, user, ctx, "application.rebuild", app)
    db.commit()
    return _detail(db, app)


@router.post("/applications/{app_id}/approve")
def approve(app_id: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db),
            ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    app = _own(db, user, app_id)
    try:
        service.approve(db, app)
    except ApplicationError as e:
        db.commit()  # keep the refreshed validation
        return _raise(e)
    _audit(db, user, ctx, "application.approve", app)
    db.commit()
    return _detail(db, app)


@router.post("/applications/{app_id}/reject")
def reject(app_id: uuid.UUID, body: RejectIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
           ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    app = _own(db, user, app_id)
    try:
        service.reject(db, app, body.reason)
    except ApplicationError as e:
        return _raise(e)
    _audit(db, user, ctx, "application.withdraw", app, reason=body.reason)
    db.commit()
    return _detail(db, app)


@router.post("/applications/{app_id}/status")
def set_status(app_id: uuid.UUID, body: StatusIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
               ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    """Track progress after you submit: applied, interview stages, rejected, offer."""
    app = _own(db, user, app_id)
    try:
        service.set_status(db, app, body.status, body.note)
    except ApplicationError as e:
        return _raise(e)
    _audit(db, user, ctx, "application.status", app, status=body.status.value)
    db.commit()
    return _detail(db, app)


@router.get("/applications/{app_id}/resume.docx")
def resume_docx(app_id: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> Response:
    app = _own(db, user, app_id)
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if rv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no resume for this application")
    data = storage.resolve(rv.file_uri).read_bytes()
    name = rv.original_filename or "resume.docx"
    return Response(data, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/applications/{app_id}/cover-letter.docx")
def cover_letter_docx(app_id: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> Response:
    app = _own(db, user, app_id)
    job = db.get(Job, app.job_id)
    name = f"cover_letter_{safe_filename(job.company, job.title)}.docx"
    return Response(
        service.cover_letter_docx(db, app),
        media_type=DOCX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/applications/{app_id}/ai-tailor", dependencies=[Depends(rate_limit("ai_tailor", 6))])
def ai_tailor(app_id: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db),
              ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    """Rewrite this package with the AI chosen in Settings. Lines the validator rejects keep your wording."""
    app = _own(db, user, app_id)
    try:
        report = tailor(db, app)
    except AiTailorError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    _audit(db, user, ctx, "application.ai_tailor", app, provider=report["provider"], model=report["model"],
           rewritten=report["lines_rewritten"], kept_original=len(report["kept_original"]))  # fmt: skip
    db.commit()
    return _detail(db, app)


@router.post("/tailor", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit("tailor", 6))])
def tailor_pasted_job(body: TailorIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
                      ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    """Paste a job -> it is stored and scored -> a package is prepared from your facts -> the AI rewrites it.
    Nothing is sent to the employer. If the AI step fails, the fact-based package is still there."""
    import hashlib
    from datetime import UTC, datetime

    from integrations.sources.base import JobPosting

    url = str(body.url) if body.url else ""
    posting = JobPosting(
        source="manual",
        external_id=hashlib.sha256(f"{url}|{body.company}|{body.title}".encode()).hexdigest()[:32],
        title=body.title,
        company=body.company,
        url=url,
        description=body.description,
        posted_at=datetime.now(UTC),
        application_url=url or None,
    )
    result = ingest_manual(db, user.id, posting)
    job_id = next((ids[0] for ids in result["job_ids"].values() if ids), None)
    if job_id is None:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "could not read this job posting")
    try:
        app = service.prepare(db, user.id, uuid.UUID(str(job_id)))
    except ApplicationError as e:
        if not e.existing_id:
            db.rollback()
            return _raise(e)
        app = db.get(Application, e.existing_id)  # already prepared for this job: tailor that one
    ai_report, ai_error = None, None
    if body.use_ai and ai_config(db, user.id)[0] is not None and app.status in service.PRE_SUBMIT:
        try:
            ai_report = tailor(db, app)
        except AiTailorError as e:
            ai_error = e.message
    _audit(db, user, ctx, "application.tailor_pasted", app, job_id=str(job_id), company=body.company,
           ai=bool(ai_report), ai_error=ai_error)  # fmt: skip
    db.commit()
    return {"application_id": str(app.id), "job_id": str(job_id), "ai_report": ai_report, "ai_error": ai_error}
