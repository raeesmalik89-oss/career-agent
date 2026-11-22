import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.application_agent.docx_render import render_resume
from agents.application_agent.package import FOCUS_CATEGORIES, build_focus_resume
from agents.match_agent.profile import build_profile
from agents.resume_agent.agent import DocumentInput, ResumeAnalyzerAgent, ResumeAnalyzerInput
from agents.resume_agent.parsing import MAX_BYTES, SUPPORTED
from agents.resume_agent.report import build_report
from agents.skill_levels import recompute_user_skills
from agents.taxonomy import get_taxonomy
from app.db.enums import Actor, Confidence, FactType, ReviewStatus, SourceType
from app.db.models import ProfileFact, ResumeVersion, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, rate_limit, request_ctx
from app.services import audit, settings_service, storage

router = APIRouter(tags=["resume"])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/resume/focus/{focus}.docx")
def focus_resume(focus: str, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> Response:
    """Download a CV built from your facts for a focus area (devops, cloud, cybersecurity)."""
    if focus not in FOCUS_CATEGORIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown focus; choose one of {sorted(FOCUS_CATEGORIES)}")
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, user.id)
    profile = build_profile(db, user.id, taxonomy, settings)
    resume = build_focus_resume(db, user.id, focus, profile, taxonomy)
    if not (resume["experience"] or resume["projects"] or resume["skills"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "upload your CV in Profile & facts first")
    return Response(
        render_resume(resume),
        media_type=DOCX,
        headers={"Content-Disposition": f'attachment; filename="{focus}_cv.docx"'},
    )


class UploadResult(BaseModel):
    run_id: str
    ok: bool
    errors: list[dict]
    actions: list[dict]


class VersionOut(BaseModel):
    id: str
    label: str
    kind: str
    format: str
    filename: str | None
    created_at: datetime


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fact_type: str
    fact_key: str
    data: dict
    source_type: str
    source_ref: dict
    review_status: str
    confidence: str


class FactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: FactType
    data: dict[str, Any]


class FactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] | None = None
    review_status: ReviewStatus | None = None
    resolve_conflicts: bool = False
    note: str | None = Field(None, max_length=500)


def _fact_out(f: ProfileFact) -> FactOut:
    return FactOut(
        id=str(f.id), fact_type=f.fact_type.value, fact_key=f.fact_key, data=f.data, source_type=f.source_type.value,
        source_ref=f.source_ref, review_status=f.review_status.value, confidence=f.confidence.value,
    )  # fmt: skip


class BulkVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


# Facts whose edits or rejection change skill levels (and therefore match scores).
SKILL_FACT_TYPES = {"skill_claim", "experience", "project"}


def _own_fact(db: Session, user: User, fact_id: uuid.UUID) -> ProfileFact:
    f = db.get(ProfileFact, fact_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")
    return f


@router.post("/resume/upload", response_model=UploadResult, dependencies=[Depends(rate_limit("resume_upload", 5))])
async def upload(
    files: list[UploadFile] = File(...),
    label: str | None = Form(None, max_length=200),
    reanalyze: bool = Form(False),
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    """Upload resumes and/or certificates (first file = primary resume). Parsed synchronously."""
    if not 1 <= len(files) <= 20:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "upload 1-20 files")
    docs: list[DocumentInput] = []
    for up in files:
        ext = Path(up.filename or "").suffix.lower()
        if ext not in SUPPORTED:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{up.filename}: use PDF, DOCX, TXT or MD")
        data = await up.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{up.filename}: larger than 10 MB")
        uri = storage.save_document(data, hashlib.sha256(data).hexdigest(), ext)
        # An explicit label only applies to a single upload; otherwise the user's filename is the label.
        doc_label = label if label and len(files) == 1 else Path(up.filename or "document").stem
        docs.append(DocumentInput(path=str(storage.resolve(uri)), label=doc_label, filename=up.filename))

    result = ResumeAnalyzerAgent().run(ResumeAnalyzerInput(user_id=user.id, documents=docs, reanalyze=reanalyze),
                                       db, user_id=user.id)  # fmt: skip
    audit.record(db, action="resume.upload", actor=Actor.user, user_id=user.id, entity_type="agent_runs",
                 entity_id=result.run_id, after={"files": [d.label for d in docs], "ok": result.ok},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return UploadResult(run_id=str(result.run_id), ok=result.ok, errors=[e.model_dump() for e in result.errors],
                        actions=[a.model_dump(mode="json") for a in result.actions])  # fmt: skip


@router.get("/resume/versions", response_model=list[VersionOut])
def versions(user: User = Depends(any_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id).order_by(ResumeVersion.created_at))
    return [VersionOut(id=str(v.id), label=v.label, kind=v.kind.value, format=v.format.value,
                       filename=v.original_filename, created_at=v.created_at) for v in rows]  # fmt: skip


@router.get("/resume/intelligence")
def intelligence(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    return build_report(db, user.id, get_taxonomy())


@router.get("/profile/facts", response_model=list[FactOut])
def list_facts(
    fact_type: FactType | None = None,
    review_status: ReviewStatus | None = None,
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
):
    q = select(ProfileFact).where(ProfileFact.user_id == user.id)
    if fact_type:
        q = q.where(ProfileFact.fact_type == fact_type)
    if review_status:
        q = q.where(ProfileFact.review_status == review_status)
    return [_fact_out(f) for f in db.scalars(q.order_by(ProfileFact.fact_type, ProfileFact.fact_key))]


@router.post("/profile/facts", response_model=FactOut, status_code=status.HTTP_201_CREATED)
def create_fact(body: FactCreate, user: User = Depends(owner_only), db: Session = Depends(get_db),
                ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    """A fact entered by the user directly: verified by definition, source = manual."""
    now = datetime.now(UTC).isoformat()
    fact = ProfileFact(
        user_id=user.id, fact_type=body.fact_type, fact_key=f"manual:{uuid.uuid4().hex[:12]}", data=body.data,
        source_type=SourceType.manual, source_ref={"sources": [{"entered_by": "user", "at": now}]},
        review_status=ReviewStatus.verified, confidence=Confidence.high,
    )  # fmt: skip
    db.add(fact)
    db.flush()
    audit.record(db, action="fact.create", actor=Actor.user, user_id=user.id, entity_type="profile_facts",
                 entity_id=fact.id, after={"fact_type": body.fact_type.value, "data": body.data},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return _fact_out(fact)


@router.patch("/profile/facts/{fact_id}", response_model=FactOut)
def patch_fact(fact_id: uuid.UUID, body: FactPatch, user: User = Depends(owner_only), db: Session = Depends(get_db),
               ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    f = _own_fact(db, user, fact_id)
    before = {"data": f.data, "review_status": f.review_status.value}
    if body.data is not None:
        data = dict(body.data)
        if not body.resolve_conflicts and f.data.get("conflicts"):
            data["conflicts"] = f.data["conflicts"]
        f.data = data
        f.source_ref = {
            "sources": [
                *f.source_ref.get("sources", []),
                {"entered_by": "user", "at": datetime.now(UTC).isoformat(), "note": body.note},
            ]
        }
        f.review_status = ReviewStatus.verified  # the user wrote it
        f.confidence = Confidence.high
    elif body.resolve_conflicts and f.data.get("conflicts"):
        f.data = {k: v for k, v in f.data.items() if k != "conflicts"}
    if body.review_status is not None:
        f.review_status = body.review_status
    if f.fact_type.value in SKILL_FACT_TYPES and (body.data is not None or body.review_status is not None):
        recompute_user_skills(db, user.id, get_taxonomy())
    audit.record(db, action="fact.update", actor=Actor.user, user_id=user.id, entity_type="profile_facts",
                 entity_id=f.id, before=before, after={"data": f.data, "review_status": f.review_status.value},
                 reason=body.note, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return _fact_out(f)


@router.post("/profile/facts/{fact_id}/verify", response_model=FactOut)
def verify_fact(fact_id: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db),
                ctx: RequestCtx = Depends(request_ctx)):  # fmt: skip
    f = _own_fact(db, user, fact_id)
    if f.data.get("conflicts"):
        raise HTTPException(status.HTTP_409_CONFLICT, "resolve this fact's conflicts before verifying it")
    before = f.review_status.value
    f.review_status = ReviewStatus.verified
    audit.record(db, action="fact.verify", actor=Actor.user, user_id=user.id, entity_type="profile_facts",
                 entity_id=f.id, before={"review_status": before}, after={"review_status": "verified"},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return _fact_out(f)


@router.post("/profile/facts/verify-bulk")
def verify_bulk(body: BulkVerifyIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
                ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    """Verify the facts you ticked. Facts with unresolved conflicts or that you rejected are skipped, not verified."""
    wanted = set(body.fact_ids)
    found = {f.id: f for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user.id,
                                                                  ProfileFact.id.in_(wanted)))}  # fmt: skip
    verified, skipped = [], []
    for fid in body.fact_ids:
        f = found.get(fid)
        if f is None:
            skipped.append({"id": str(fid), "reason": "not found"})
        elif f.data.get("conflicts"):
            skipped.append({"id": str(fid), "reason": "resolve conflicts first"})
        elif f.review_status == ReviewStatus.rejected:
            skipped.append({"id": str(fid), "reason": "rejected; restore it first"})
        elif f.review_status != ReviewStatus.verified:
            f.review_status = ReviewStatus.verified
            verified.append(str(fid))
            audit.record(db, action="fact.verify", actor=Actor.user, actor_detail="bulk", user_id=user.id,
                         entity_type="profile_facts", entity_id=f.id, before={"review_status": "pending"},
                         after={"review_status": "verified"}, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return {"verified": verified, "skipped": skipped}
