"""Common contract for every agent: a typed input, a structured AgentResult, and a persisted agent_runs row."""

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.enums import Confidence, RunStatus
from app.db.models import AgentRun

log = logging.getLogger(__name__)


class AgentAction(BaseModel):
    type: str
    target: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AgentResult(BaseModel):
    agent_name: str
    run_id: uuid.UUID
    input_summary: str
    actions: list[AgentAction] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low"] | None = None
    errors: list[AgentError] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ok(self) -> bool:
        return not self.errors


class AgentContext:
    """Passed to Agent.execute; collects actions/errors so agents stay free of persistence code."""

    def __init__(self, run_id: uuid.UUID, db: Session, user_id: uuid.UUID | None):
        self.run_id = run_id
        self.db = db
        self.user_id = user_id
        self.actions: list[AgentAction] = []
        self.errors: list[AgentError] = []

    def act(self, type_: str, target: str | None = None, **detail: Any) -> None:
        self.actions.append(AgentAction(type=type_, target=target, detail=detail))

    def error(self, code: str, message: str, retryable: bool = False) -> None:
        self.errors.append(AgentError(code=code, message=message, retryable=retryable))


InputT = TypeVar("InputT", bound=BaseModel)


class Agent(ABC, Generic[InputT]):
    name: ClassVar[str]

    @abstractmethod
    def summarize_input(self, payload: InputT) -> str:
        """Short, PII-free description of the input (IDs and counts, not content)."""

    @abstractmethod
    def execute(self, payload: InputT, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        """Do the work. Return (output, confidence). Record side effects with ctx.act()."""

    def run(
        self,
        payload: InputT,
        db: Session,
        *,
        user_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
    ) -> AgentResult:
        run_id = uuid.uuid4()
        summary = self.summarize_input(payload)
        row = AgentRun(
            id=run_id,
            pipeline_run_id=pipeline_run_id,
            user_id=user_id,
            agent_name=self.name,
            status=RunStatus.running,
            input_summary=summary,
        )
        db.add(row)
        db.flush()
        ctx = AgentContext(run_id, db, user_id)
        output: dict[str, Any] = {}
        confidence: Confidence | None = None
        try:
            output, confidence = self.execute(payload, ctx)
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded, never swallowed silently
            log.exception("agent %s failed (run %s)", self.name, run_id)
            ctx.error("unhandled_exception", f"{type(exc).__name__}: {exc}")

        result = AgentResult(
            agent_name=self.name,
            run_id=run_id,
            input_summary=summary,
            actions=ctx.actions,
            output=output,
            confidence=confidence.value if confidence else None,
            errors=ctx.errors,
        )
        dumped = result.model_dump(mode="json")
        row.status = RunStatus.failed if ctx.errors else RunStatus.succeeded
        row.actions = dumped["actions"]
        row.output = dumped["output"]
        row.errors = dumped["errors"]
        row.confidence = confidence
        row.finished_at = result.timestamp
        db.flush()
        return result
