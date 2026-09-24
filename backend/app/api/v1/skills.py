import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.skill_agent import gaps as gap_engine
from agents.skill_agent import learning
from agents.taxonomy import get_taxonomy
from app.db.enums import Actor
from app.db.models import LearningItem, Skill, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.services import audit

router = APIRouter(tags=["skills"])


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str] | None = Field(None, max_length=20)
    top: int = Field(5, ge=1, le=10)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["todo", "in_progress", "done"]


def _item_out(i: LearningItem, key: str) -> dict:
    return {
        "id": str(i.id),
        "skill": key,
        "kind": i.kind.value,
        "title": i.title,
        "content_md": i.content_md,
        "status": i.status,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
    }


@router.get("/skills/gaps")
def skill_gaps(
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
    window: int = Query(30),
) -> dict:
    """Skills your target jobs ask for, with your evidence status and a priority score."""
    if window not in (1, 7, 30):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "window must be 1, 7 or 30 days")
    report = gap_engine.analyse(db, user.id, window)
    if user.role.value == "owner":
        gap_engine.save_report(db, user.id, report)
        db.commit()
    guides = learning.get_guides()
    for g in report["gaps"]:
        g["guide"] = g["skill"] in guides
    return report


@router.get("/learning/skills/{key}")
def skill_guide(key: str, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    if key not in get_taxonomy().skills:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown skill")
    g = learning.get_guides().get(key)
    guide = {**g, "curated": True} if g else learning.fallback_guide(key)
    skill = db.scalars(select(Skill).where(Skill.canonical_name == key)).first()
    items = (
        db.scalars(select(LearningItem).where(LearningItem.user_id == user.id, LearningItem.skill_id == skill.id)).all()
        if skill
        else []
    )
    out = {
        "guide": {k: v for k, v in guide.items() if k != "concept_map"},
        "evidence": learning.evidence_status(db, user.id, key),
        "items": [_item_out(i, key) for i in items],
        "concept_map": None,
    }
    if g:
        cmap = g["concept_map"]
        out["concept_map"] = {
            "tree": learning.concept_map_tree(cmap),
            "mermaid": learning.concept_map_mermaid(cmap),
            "markdown": learning.concept_map_markdown(cmap),
        }
    return out


@router.post("/learning/plan")
def plan(body: PlanIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
         ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    """Add learning items for the chosen skills, or for your top gap skills that have a guide."""
    keys = body.skills
    if keys is None:
        report = gap_engine.analyse(db, user.id, 30)
        guides = learning.get_guides()
        keys = [g["skill"] for g in report["gaps"] if g["status"] != "have" and g["skill"] in guides][: body.top]
    created = learning.plan_items(db, user.id, keys)
    audit.record(db, action="learning.plan", actor=Actor.user, user_id=user.id, entity_type="learning_items",
                 after={"skills": keys, "created": len(created)}, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return {"skills": keys, "created": len(created)}


@router.get("/learning")
def learning_items(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(LearningItem, Skill.canonical_name, Skill.display_name)
        .join(Skill, Skill.id == LearningItem.skill_id)
        .where(LearningItem.user_id == user.id)
        .order_by(LearningItem.created_at)
    ).all()
    by_skill: dict[str, dict] = defaultdict(lambda: {"items": []})
    for item, key, name in rows:
        entry = by_skill[key]
        entry["skill"], entry["name"] = key, name or key
        entry["items"].append(_item_out(item, key))
    out = []
    for key, entry in by_skill.items():
        done = sum(i["status"] == "done" for i in entry["items"])
        out.append(
            entry | {"done": done, "total": len(entry["items"]), "evidence": learning.evidence_status(db, user.id, key)}
        )
    return {"skills": out}


@router.patch("/learning/items/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemIn, user: User = Depends(owner_only), db: Session = Depends(get_db),
                ctx: RequestCtx = Depends(request_ctx)) -> dict:  # fmt: skip
    """Track progress. Completing items never changes a skill level: only evidence does."""
    item = db.get(LearningItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "learning item not found")
    item.status = body.status
    item.completed_at = datetime.now(UTC) if body.status == "done" else None
    audit.record(db, action="learning.item_status", actor=Actor.user, user_id=user.id, entity_type="learning_items",
                 entity_id=item.id, after={"status": body.status}, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    key = db.get(Skill, item.skill_id).canonical_name
    return _item_out(item, key)
