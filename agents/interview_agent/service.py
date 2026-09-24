"""Mock interview sessions: one question at a time; the model answer is revealed only after you answer."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.interview_agent.bank import KeyPoint, get_bank
from agents.interview_agent.pack import SECTION_TITLES, WEAK, generate_pack
from agents.interview_agent.rubric import DISCLAIMER, evaluate
from app.db.models import InterviewAnswer, InterviewQuestion, InterviewSession

MODES = {"pack", *SECTION_TITLES}


class InterviewError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _points(q: InterviewQuestion) -> list[KeyPoint]:
    return [KeyPoint(p[0], tuple(p[1:]) or (p[0],)) for p in q.key_points]


def start_session(db: Session, user_id: uuid.UUID, mode: str, count: int, day: date | None = None) -> InterviewSession:
    if mode not in MODES:
        raise InterviewError(422, f"mode must be one of {sorted(MODES)}")
    day = day or datetime.now(UTC).date()
    pack = generate_pack(db, user_id, day)
    pool = [q for q in pack if mode == "pack" or q.section == mode]
    if not pool:
        raise InterviewError(422, f"no questions in today's pack for {mode}")
    if mode == "pack":
        # a mixed interview: take questions round-robin across the sections
        by_section = defaultdict(list)
        for q in pool:
            by_section[q.section].append(q)
        mixed = []
        while any(by_section.values()) and len(mixed) < count:
            for s in list(by_section):
                if by_section[s] and len(mixed) < count:
                    mixed.append(by_section[s].pop(0))
        pool = mixed
    session = InterviewSession(
        user_id=user_id,
        mode=mode,
        summary={"queue": [str(q.id) for q in pool[:count]], "pack_date": day.isoformat()},
    )
    db.add(session)
    db.flush()
    return session


def _answered(db: Session, session: InterviewSession) -> dict[str, InterviewAnswer]:
    return {
        str(a.question_id): a
        for a in db.scalars(select(InterviewAnswer).where(InterviewAnswer.session_id == session.id))
        if a.question_id
    }


def next_question(db: Session, session: InterviewSession) -> dict | None:
    done = _answered(db, session)
    queue = session.summary.get("queue", [])
    for i, qid in enumerate(queue):
        if qid not in done:
            q = db.get(InterviewQuestion, uuid.UUID(qid))
            if q is None:
                continue
            return {
                "question_id": qid,
                "index": i + 1,
                "total": len(queue),
                "section": q.section,
                "section_title": SECTION_TITLES.get(q.section, q.section),
                "difficulty": q.difficulty,
                "question": q.question,
                # what is being tested is fine to show; the model answer is not
                "tests": q.testing_what,
            }
    return None


def answer(db: Session, session: InterviewSession, question_id: uuid.UUID, text: str) -> dict:
    if session.ended_at is not None:
        raise InterviewError(409, "this session has ended")
    if str(question_id) not in session.summary.get("queue", []):
        raise InterviewError(404, "that question is not part of this session")
    if str(question_id) in _answered(db, session):
        raise InterviewError(409, "already answered")
    q = db.get(InterviewQuestion, question_id)
    bank_q = get_bank().get(q.bank_id or "")
    ev = evaluate(
        text,
        _points(q),
        ideal=q.ideal_answer,
        behavioural=q.section == "hr",
        red_flags=bank_q.red_flags if bank_q else (),
        anchored=(q.bank_id or "").startswith("metric:"),
    )
    row = InterviewAnswer(
        session_id=session.id,
        question_id=q.id,
        question_text=q.question,
        user_answer=text,
        score=ev.score,
        mistakes=ev.mistakes,
        missing_concepts=ev.missing,
        improved_answer=q.ideal_answer,
        professional_version=q.ideal_answer,
        spoken_version=q.spoken_answer or q.ideal_answer,
        rubric=ev.rubric,
        bank_id=q.bank_id,
    )
    db.add(row)
    db.flush()
    scores = [a.score for a in _answered(db, session).values()]
    session.avg_score = Decimal(str(round(sum(scores) / len(scores), 2)))
    if len(scores) >= len(session.summary.get("queue", [])):
        session.ended_at = datetime.now(UTC)
    db.flush()
    return feedback(q, row)


def feedback(q: InterviewQuestion, a: InterviewAnswer) -> dict:
    return {
        "question_id": str(q.id),
        "question": q.question,
        "your_answer": a.user_answer,
        "score": a.score,
        "rubric": a.rubric,
        "covered": [p[0] for p in q.key_points if p[0] not in a.missing_concepts],
        "missing_concepts": a.missing_concepts,
        "mistakes": a.mistakes,
        "common_mistakes": [m for m in q.common_mistakes.split("\n") if m],
        "model_answer": a.improved_answer,
        "spoken_version": a.spoken_version,
        "follow_up": q.follow_up,
        "disclaimer": DISCLAIMER,
    }


def end_session(db: Session, session: InterviewSession) -> None:
    session.ended_at = session.ended_at or datetime.now(UTC)
    db.flush()


def session_detail(db: Session, session: InterviewSession) -> dict:
    answers = _answered(db, session)
    items = []
    for qid in session.summary.get("queue", []):
        q = db.get(InterviewQuestion, uuid.UUID(qid))
        a = answers.get(qid)
        if q is None:
            continue
        items.append(feedback(q, a) if a else {"question_id": qid, "question": q.question, "score": None})
    return {
        "id": str(session.id),
        "mode": session.mode,
        "mode_title": "Mixed (today's pack)" if session.mode == "pack" else SECTION_TITLES.get(session.mode),
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "avg_score": float(session.avg_score) if session.avg_score is not None else None,
        "answered": len(answers),
        "total": len(session.summary.get("queue", [])),
        "items": items,
        "next": None if session.ended_at else next_question(db, session),
        "disclaimer": DISCLAIMER,
    }


def stats(db: Session, user_id: uuid.UUID) -> dict:
    rows = db.execute(
        select(InterviewAnswer, InterviewQuestion.section, InterviewQuestion.question)
        .join(InterviewSession, InterviewSession.id == InterviewAnswer.session_id)
        .outerjoin(InterviewQuestion, InterviewQuestion.id == InterviewAnswer.question_id)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewAnswer.at)
    ).all()
    by_section: dict[str, list[int]] = defaultdict(list)
    latest: dict[str, tuple[int, str, str]] = {}
    by_day: dict[str, list[int]] = defaultdict(list)
    for a, section, question in rows:
        by_section[section or "other"].append(a.score)
        by_day[a.at.date().isoformat()].append(a.score)
        latest[a.bank_id or str(a.question_id)] = (a.score, question or a.question_text, section or "other")
    since = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    return {
        "answers": len(rows),
        "sessions": len({a.session_id for a, _, _ in rows}),
        "average": round(sum(a.score for a, _, _ in rows) / len(rows), 1) if rows else None,
        "by_section": {
            s: {"title": SECTION_TITLES.get(s, s), "answers": len(v), "average": round(sum(v) / len(v), 1)}
            for s, v in by_section.items()
        },
        "trend": [{"day": d, "average": round(sum(v) / len(v), 1)} for d, v in sorted(by_day.items()) if d >= since],
        "weakest": sorted(
            ({"question": q, "section": s, "last_score": sc} for sc, q, s in latest.values() if sc < WEAK),
            key=lambda x: x["last_score"],
        )[:10],
        "disclaimer": DISCLAIMER,
    }
