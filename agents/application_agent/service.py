"""Application lifecycle: prepare -> validate -> policy -> (you approve) -> assisted submit -> status tracking.

MVP submission is assisted: the package is approved here, you submit it on the employer's site yourself, and
mark it applied. Automated form submission (Playwright) is not part of this milestone.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.application_agent.docx_render import render_cover_letter, render_resume, safe_filename
from agents.application_agent.package import PLACEHOLDER_RX, build_answers, build_cover_letter, build_resume
from agents.application_agent.policy import decide_prepare, decide_submission
from agents.application_agent.validator import validate_item, validate_resume
from agents.job_agent.ingest import norm_title
from agents.match_agent.agent import job_skill_views, job_view, run_matching
from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.enums import Actor, AnswerCategory, ApplicationMode, ApplicationStatus, FileFormat, ResumeKind
from app.db.enums import ValidationStatus as VS
from app.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationEvent,
    Job,
    JobMatch,
    JobSource,
    JobSourceLink,
    ProfileFact,
    ResumeProfile,
    ResumeVersion,
)
from app.services import settings_service, storage

COVER_LETTER_Q = "Cover letter"
DUPLICATE_WINDOW_DAYS = 60
PRE_SUBMIT = {ApplicationStatus.prepared, ApplicationStatus.pending_approval, ApplicationStatus.failed}
TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.awaiting_manual_submit: {ApplicationStatus.applied, ApplicationStatus.withdrawn},
    ApplicationStatus.approved: {ApplicationStatus.applied, ApplicationStatus.withdrawn},
    ApplicationStatus.applied: {
        ApplicationStatus.interview,
        ApplicationStatus.technical_interview,
        ApplicationStatus.hr_interview,
        ApplicationStatus.rejected,
        ApplicationStatus.offer,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.interview: {
        ApplicationStatus.technical_interview,
        ApplicationStatus.hr_interview,
        ApplicationStatus.rejected,
        ApplicationStatus.offer,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.technical_interview: {
        ApplicationStatus.hr_interview,
        ApplicationStatus.rejected,
        ApplicationStatus.offer,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.hr_interview: {ApplicationStatus.rejected, ApplicationStatus.offer, ApplicationStatus.withdrawn},
    ApplicationStatus.offer: {ApplicationStatus.withdrawn},
}


class ApplicationError(Exception):
    def __init__(self, status_code: int, message: str, existing_id: uuid.UUID | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.existing_id = existing_id


def _event(db: Session, app: Application, event_type: str, actor: Actor, **detail) -> None:
    db.add(ApplicationEvent(application_id=app.id, event_type=event_type, actor=actor, detail=detail))
    app.last_update = datetime.now(UTC)


def _current_match(db: Session, user_id: uuid.UUID, job: Job) -> JobMatch | None:
    return db.scalars(
        select(JobMatch).where(
            JobMatch.user_id == user_id, JobMatch.job_id == job.id, JobMatch.job_content_version == job.content_version
        )
    ).first()


def find_duplicate(db: Session, user_id: uuid.UUID, job: Job) -> Application | None:
    """Same job, or the same company with a near-identical title within 60 days (a repost)."""
    same = db.scalars(select(Application).where(Application.user_id == user_id, Application.job_id == job.id)).first()
    if same:
        return same
    since = datetime.now(UTC) - timedelta(days=DUPLICATE_WINDOW_DAYS)
    mine = set(norm_title(job.title).split())
    for app, other in db.execute(
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(
            Application.user_id == user_id,
            Job.company_normalized == job.company_normalized,
            Application.created_at >= since,
            Application.status != ApplicationStatus.withdrawn,
        )
    ).all():
        theirs = set(norm_title(other.title).split())
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= 0.8:
            return app
    return None


def _facts_by_id(db: Session, user_id: uuid.UUID) -> dict[str, ProfileFact]:
    return {str(f.id): f for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id))}


def _source_allows_auto(db: Session, job: Job) -> bool:
    rows = db.scalars(
        select(JobSource.auto_apply_allowed)
        .join(JobSourceLink, JobSourceLink.source_id == JobSource.id)
        .where(JobSourceLink.job_id == job.id)
    ).all()
    return bool(rows) and all(rows)


def prepare(db: Session, user_id: uuid.UUID, job_id: uuid.UUID, *, requested_by_user: bool = True) -> Application:
    job = db.get(Job, job_id)
    if job is None:
        raise ApplicationError(404, "job not found")
    dup = find_duplicate(db, user_id, job)
    if dup is not None:
        raise ApplicationError(409, "an application for this job (or a repost of it) already exists", dup.id)
    match = _current_match(db, user_id, job)
    if match is None:
        run_matching(db, user_id, job_ids=[job.id])
        match = _current_match(db, user_id, job)
    settings, _ = settings_service.get_effective(db, user_id)
    decision = decide_prepare(
        score=float(match.estimated_fit_score) if match else 0.0,
        knockouts=match.knockouts if match else [],
        settings=settings,
        requested_by_user=requested_by_user,
    )
    if decision.outcome == "skip":
        raise ApplicationError(422, "policy does not prepare this job automatically")

    app = Application(
        user_id=user_id,
        job_id=job.id,
        match_id=match.id if match else None,
        status=ApplicationStatus.prepared,
        mode=ApplicationMode.assisted,
        application_url=job.employer_url or job.application_url or job.url,
        idempotency_key=hashlib.sha256(f"{user_id}|{job.id}|{job.content_version}".encode()).hexdigest(),
        policy_decision={"prepare": decision.dump()},
    )
    db.add(app)
    db.flush()
    _event(db, app, "prepared", Actor.agent, score=float(match.estimated_fit_score) if match else None)
    _build(db, app, job)
    return app


def _build(db: Session, app: Application, job: Job) -> None:
    """(Re)generate the resume, cover letter and answers for an application that is not yet approved."""
    user_id = app.user_id
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, user_id)
    profile = build_profile(db, user_id, taxonomy, settings)
    view = job_view(job, job_skill_views(db, [job.id]).get(job.id, []))

    resume = build_resume(db, user_id, view, profile, taxonomy)
    letter = build_cover_letter(db, user_id, view, profile, resume)
    answers = build_answers(db, user_id, view, profile, settings, resume)

    data = render_resume(resume)
    sha = hashlib.sha256(data + str(app.id).encode()).hexdigest()
    uri = storage.save_document(data, sha, ".docx")
    rp = db.scalars(
        select(ResumeProfile).where(ResumeProfile.user_id == user_id, ResumeProfile.is_active.is_(True))
    ).first()
    if rp is None:
        raise ApplicationError(422, "import your resume first (no active resume profile)")
    name = f"resume_{safe_filename(job.company, job.title)}.docx"
    existing = db.scalars(
        select(ResumeVersion).where(ResumeVersion.user_id == user_id, ResumeVersion.sha256 == sha)
    ).first()
    rv = existing or ResumeVersion(
        user_id=user_id,
        profile_id=rp.id,
        kind=ResumeKind.tailored,
        job_id=job.id,
        label=f"Tailored for {job.company}: {job.title}"[:200],
        original_filename=name[:300],
        file_uri=uri,
        format=FileFormat.docx,
        sha256=sha,
    )
    rv.parsed = {"resume": resume}
    if existing is None:
        db.add(rv)
    db.flush()
    app.resume_version_id = rv.id

    for old in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)):
        db.delete(old)
    meta = {}
    letter_ids = sorted({fid for p in letter for fid in p.fact_ids})
    rows = [(COVER_LETTER_Q, "open_ended", "\n\n".join(p.text for p in letter), letter_ids,
             sorted({d for p in letter for d in p.derived}), False)]  # fmt: skip
    rows += [
        (a.question, a.category, a.item.text, a.item.fact_ids, a.item.derived, a.item.user_written) for a in answers
    ]
    for question, category, text, ids, derived, user_written in rows:
        ans = ApplicationAnswer(
            application_id=app.id,
            question=question,
            answer=text,
            category=AnswerCategory(category),
            cited_fact_ids=ids,
            validation_status=VS.needs_approval,
        )
        db.add(ans)
        db.flush()
        meta[str(ans.id)] = {"derived": derived, "user_written": user_written}
    app.policy_decision = {**app.policy_decision, "answers_meta": meta}
    _event(db, app, "package_built", Actor.agent, resume_version=str(rv.id), answers=len(rows))
    revalidate(db, app)


def revalidate(db: Session, app: Application) -> dict:
    """Re-check every item against the current facts and re-run the submission policy. Returns the summary."""
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, app.user_id)
    profile = build_profile(db, app.user_id, taxonomy, settings)
    facts = _facts_by_id(db, app.user_id)
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    resume_check = validate_resume(rv.parsed["resume"], facts, profile, taxonomy) if rv else {"items": [], "counts": {}}
    meta = app.policy_decision.get("answers_meta", {})
    answers = []
    for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)):
        m = meta.get(str(a.id), {})
        if not a.answer.strip():
            a.validation_status, a.validation_notes = VS.valid, ["left empty: not used"]
        else:
            v = validate_item(
                {"text": a.answer, "fact_ids": a.cited_fact_ids, "derived": m.get("derived", []),
                 "user_written": m.get("user_written", False)},
                facts, profile, taxonomy,
            )  # fmt: skip
            status = v.status
            notes = list(v.notes)
            if status == "valid" and a.category.value != "factual" and not a.approved_by_user_at:
                status, notes = "needs_approval", [*notes, f"{a.category.value.replace('_', ' ')} question: you decide"]
            a.validation_status, a.validation_notes = VS(status), notes
        answers.append({"category": a.category.value, "validation_status": a.validation_status.value,
                        "approved": a.approved_by_user_at is not None})  # fmt: skip
    job = db.get(Job, app.job_id)
    match = db.get(JobMatch, app.match_id) if app.match_id else None
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    auto_today = db.scalar(
        select(func.count(Application.id)).where(
            Application.user_id == app.user_id,
            Application.mode == ApplicationMode.auto,
            Application.submitted_at >= today,
        )
    )
    decision = decide_submission(
        settings=settings,
        source_auto_apply_allowed=_source_allows_auto(db, job),
        answers=answers,
        resume_counts=resume_check["counts"],
        match_confidence=match.score_confidence.value if match else None,
        pk_eligibility=job.pk_eligibility.value,
        auto_submits_today=auto_today or 0,
    )
    app.policy_decision = {**app.policy_decision, "submission": decision.dump(), "resume_validation": resume_check}
    if app.status in (ApplicationStatus.prepared, ApplicationStatus.failed):
        app.status = ApplicationStatus.pending_approval  # MVP: every package goes to your approval queue
    db.flush()
    return {"resume": resume_check["counts"], "answers": answers, "submission": decision.outcome}


def _blockers(db: Session, app: Application) -> list[str]:
    out = []
    counts = app.policy_decision.get("resume_validation", {}).get("counts", {})
    if counts.get("unsupported"):
        out.append(f"{counts['unsupported']} resume line(s) are unsupported by your facts")
    for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)):
        if a.validation_status == VS.unsupported:
            out.append(f"“{a.question}” contains an unsupported claim")
        if PLACEHOLDER_RX.search(a.answer):
            out.append(f"“{a.question}” still has [bracketed] text to replace (or clear it if the form does not ask)")
    return out


def edit_answer(db: Session, app: Application, answer_id: uuid.UUID, text: str) -> ApplicationAnswer:
    if app.status not in PRE_SUBMIT:
        raise ApplicationError(409, "this application is already approved; withdraw it to change answers")
    a = db.get(ApplicationAnswer, answer_id)
    if a is None or a.application_id != app.id:
        raise ApplicationError(404, "answer not found")
    a.answer = text
    a.approved_by_user_at = None
    meta = dict(app.policy_decision.get("answers_meta", {}))
    meta[str(a.id)] = {**meta.get(str(a.id), {}), "user_written": True}
    app.policy_decision = {**app.policy_decision, "answers_meta": meta}
    _event(db, app, "answer_edited", Actor.user, question=a.question)
    revalidate(db, app)
    return a


def rebuild(db: Session, app: Application) -> None:
    if app.status not in PRE_SUBMIT:
        raise ApplicationError(409, "only a package that is not yet approved can be rebuilt")
    _build(db, app, db.get(Job, app.job_id))


def approve(db: Session, app: Application) -> None:
    if app.status not in PRE_SUBMIT:
        raise ApplicationError(409, f"cannot approve an application that is {app.status.value}")
    revalidate(db, app)
    blockers = _blockers(db, app)
    if blockers:
        raise ApplicationError(422, "; ".join(blockers))
    now = datetime.now(UTC)
    for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)):
        a.approved_by_user_at = now
    app.status = ApplicationStatus.approved
    _event(db, app, "approved", Actor.user)
    # MVP: assisted apply. You open the application page, paste the approved answers and upload the resume.
    app.status = ApplicationStatus.awaiting_manual_submit
    # an employer link added after the package was prepared wins over the stored (often aggregator) link
    job = db.get(Job, app.job_id)
    app.application_url = (job.employer_url if job else None) or app.application_url
    _event(db, app, "awaiting_manual_submit", Actor.system, url=app.application_url)


def reject(db: Session, app: Application, reason: str | None) -> None:
    if app.status not in PRE_SUBMIT | {ApplicationStatus.approved, ApplicationStatus.awaiting_manual_submit}:
        raise ApplicationError(409, f"cannot withdraw an application that is {app.status.value}; mark it instead")
    app.status = ApplicationStatus.withdrawn
    _event(db, app, "withdrawn", Actor.user, reason=reason)


def set_status(db: Session, app: Application, new: ApplicationStatus, note: str | None) -> None:
    if new not in TRANSITIONS.get(app.status, set()):
        raise ApplicationError(409, f"cannot go from {app.status.value} to {new.value}")
    app.status = new
    if new == ApplicationStatus.applied:
        app.submitted_at = datetime.now(UTC)
    _event(db, app, f"status_{new.value}", Actor.user, note=note)


def cover_letter_docx(db: Session, app: Application) -> bytes:
    a = db.scalars(
        select(ApplicationAnswer).where(
            ApplicationAnswer.application_id == app.id, ApplicationAnswer.question == COVER_LETTER_Q
        )
    ).first()
    return render_cover_letter([p for p in (a.answer if a else "").split("\n\n") if p.strip()])
