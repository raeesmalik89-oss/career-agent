from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, AuditLog, User
from app.db.session import get_db
from app.deps import owner_only

router = APIRouter(tags=["ops"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    at: datetime
    actor: str
    actor_detail: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    before: dict | None
    after: dict | None
    reason: str | None
    request_id: str | None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str | None
    agent_name: str
    status: str
    input_summary: str
    actions: list
    output: dict
    confidence: str | None
    errors: list
    started_at: datetime
    finished_at: datetime | None


def _audit_out(r: AuditLog) -> AuditOut:
    return AuditOut.model_validate({**r.__dict__, "id": str(r.id), "actor": r.actor.value})


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    action: str | None = Query(None, max_length=80),
    entity_type: str | None = Query(None, max_length=50),
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    q = select(AuditLog).where(AuditLog.user_id == user.id)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if before:
        q = q.where(AuditLog.at < before)
    return [_audit_out(r) for r in db.scalars(q.order_by(AuditLog.at.desc()).limit(limit))]


@router.get("/agent-runs", response_model=list[AgentRunOut])
def agent_runs(
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    agent_name: str | None = Query(None, max_length=60),
    limit: int = Query(50, ge=1, le=500),
):
    q = select(AgentRun).where((AgentRun.user_id == user.id) | AgentRun.user_id.is_(None))
    if agent_name:
        q = q.where(AgentRun.agent_name == agent_name)
    rows = db.scalars(q.order_by(AgentRun.started_at.desc()).limit(limit))
    return [
        AgentRunOut.model_validate(
            {
                **r.__dict__,
                "id": str(r.id),
                "pipeline_run_id": str(r.pipeline_run_id) if r.pipeline_run_id else None,
                "status": r.status.value,
                "confidence": r.confidence.value if r.confidence else None,
            }
        )
        for r in rows
    ]
