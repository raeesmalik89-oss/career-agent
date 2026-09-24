import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.interview_agent import service
from agents.interview_agent.pack import PACK_ORDER, SECTIONS, generate_pack
from agents.interview_agent.rubric import DISCLAIMER
from agents.interview_agent.service import InterviewError
from app.db.enums import Actor
from app.db.models import InterviewQuestion, InterviewSession, User
from app.db.session import get_db
from app.deps import WRITER_ROLES, RequestCtx, any_user, owner_only, request_ctx
from app.services import audit

router = APIRouter(prefix="/interview", tags=["interview"])


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field("pack", max_length=20)
    count: int = Field(10, ge=1, le=30)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    answer: str = Field(max_length=8000)


def _day(value: str) -> date:
    if value == "today":
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date must be YYYY-MM-DD or 'today'") from e


def _own_session(db: Session, user: User, sid: uuid.UUID) -> InterviewSession:
    s = db.get(InterviewSession, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return s


def _raise(e: InterviewError):
    raise HTTPException(e.status_code, str(e))


def _pack_out(day: date, rows: list[InterviewQuestion]) -> dict:
    sections = []
    for key, title in SECTIONS:
        qs = [q for q in rows if q.section == key]
        sections.append(
            {
                "key": key,
                "title": title,
                "questions": [
                    {
                        "id": str(q.id),
                        "bank_id": q.bank_id,
                        "question": q.question,
                        "difficulty": q.difficulty,
                        "tests": q.testing_what,
                        "key_points": [p[0] for p in q.key_points],
                        "model_answer": q.ideal_answer,
                        "spoken_answer": q.spoken_answer,
                        "common_mistakes": [m for m in q.common_mistakes.split("\n") if m],
                        "follow_up": q.follow_up,
                    }
                    for q in qs
                ],
            }
        )
    return {"date": day.isoformat(), "total": len(rows), "sections": sections, "disclaimer": DISCLAIMER}


@router.get("/packs/{day}")
def get_pack(day: str, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    """Today's pack is created on first request; older packs are returned as they were."""
    d = _day(day)
    rows = list(db.scalars(select(InterviewQuestion).where(InterviewQuestion.user_id == user.id,
                                                             InterviewQuestion.pack_date == d)
                           .order_by(*PACK_ORDER)))  # fmt: skip
    if not rows and d == datetime.now(UTC).date() and user.role in WRITER_ROLES:
        rows = generate_pack(db, user.id, d)
        db.commit()
    return _pack_out(d, rows)


@router.post("/packs/today/regenerate")
def regenerate(user: User = Depends(owner_only), db: Session = Depends(get_db),
               ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    d = datetime.now(UTC).date()
    rows = generate_pack(db, user.id, d, regenerate=True)
    audit.record(db, action="interview.pack_regenerate", actor=Actor.user, user_id=user.id, entity_type="interview",
                 after={"questions": len(rows)}, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return _pack_out(d, rows)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def start(body: SessionIn, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    try:
        s = service.start_session(db, user.id, body.mode, body.count)
    except InterviewError as e:
        _raise(e)
    db.commit()
    return service.session_detail(db, s)


@router.get("/sessions")
def list_sessions(user: User = Depends(any_user), db: Session = Depends(get_db),
                  limit: int = Query(20, ge=1, le=100)) -> list[dict]:  # fmt: skip
    rows = db.scalars(
        select(InterviewSession).where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.started_at.desc()).limit(limit)
    )  # fmt: skip
    return [
        {
            "id": str(s.id),
            "mode": s.mode,
            "started_at": s.started_at.isoformat(),
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "avg_score": float(s.avg_score) if s.avg_score is not None else None,
            "total": len(s.summary.get("queue", [])),
        }  # fmt: skip
        for s in rows
    ]


@router.get("/sessions/{sid}")
def get_session(sid: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    return service.session_detail(db, _own_session(db, user, sid))


@router.get("/sessions/{sid}/next")
def next_q(sid: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    nxt = service.next_question(db, _own_session(db, user, sid))
    return nxt or {"done": True}


@router.post("/sessions/{sid}/answer")
def answer(sid: uuid.UUID, body: AnswerIn, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    s = _own_session(db, user, sid)
    try:
        out = service.answer(db, s, body.question_id, body.answer)
    except InterviewError as e:
        _raise(e)
    db.commit()
    return out | {"next": service.next_question(db, s), "session_avg": float(s.avg_score) if s.avg_score else None}


@router.post("/sessions/{sid}/end")
def end(sid: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    s = _own_session(db, user, sid)
    service.end_session(db, s)
    db.commit()
    return service.session_detail(db, s)


@router.get("/stats")
def stats(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    return service.stats(db, user.id)
