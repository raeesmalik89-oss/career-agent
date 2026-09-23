import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import inspect, select

from agents.base import Agent, AgentContext
from app.core import crypto
from app.core.security import hash_password, verify_password
from app.db.enums import Confidence, RunStatus
from app.db.models import AgentRun
from app.db.types import Embedding


def test_crypto_roundtrip_and_tamper_detection():
    blob = crypto.encrypt("ghp_secret_token", b"ctx")
    assert b"ghp_secret_token" not in blob
    assert crypto.decrypt(blob, b"ctx") == "ghp_secret_token"
    assert crypto.encrypt("same", b"") != crypto.encrypt("same", b"")  # fresh nonce/key each time
    with pytest.raises(Exception):  # noqa: B017 - InvalidTag
        crypto.decrypt(blob, b"other-context")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(Exception):  # noqa: B017
        crypto.decrypt(tampered, b"ctx")


def test_password_hashing():
    h = hash_password("s3cure-passphrase")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cure-passphrase", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_embedding_dimension_enforced():
    with pytest.raises(ValueError, match="1024"):
        Embedding().process_bind_param([0.1, 0.2], None)


def test_migration_creates_every_table(engine):
    tables = set(inspect(engine).get_table_names())
    expected = {
        "users", "resume_profiles", "resume_versions", "github_profiles", "github_repositories",
        "github_evidence", "jobs", "job_skills", "job_matches", "applications", "application_answers",
        "application_events", "skills", "skill_gaps", "interview_questions", "interview_sessions",
        "interview_answers", "concept_maps", "daily_reports", "agent_runs", "audit_logs", "notifications",
        "profile_facts", "user_skills", "job_sources", "jobs_raw", "job_source_links", "secrets",
        "settings_versions", "auth_sessions", "learning_items", "knowledge_edges",
    }  # fmt: skip
    assert expected <= tables


class EchoIn(BaseModel):
    items: list[str]
    fail: bool = False


class EchoAgent(Agent[EchoIn]):
    name = "echo_agent"

    def summarize_input(self, payload: EchoIn) -> str:
        return f"{len(payload.items)} items"

    def execute(self, payload: EchoIn, ctx: AgentContext):
        for i in payload.items:
            ctx.act("echo", target=i)
        if payload.fail:
            raise RuntimeError("boom")
        return {"count": len(payload.items)}, Confidence.high


def test_agent_run_is_recorded(db):
    pipeline = uuid.uuid4()
    result = EchoAgent().run(EchoIn(items=["a", "b"]), db, pipeline_run_id=pipeline)
    assert result.ok and result.output == {"count": 2} and result.confidence == "high"
    row = db.get(AgentRun, result.run_id)
    assert row.status == RunStatus.succeeded
    assert row.input_summary == "2 items" and len(row.actions) == 2
    assert row.pipeline_run_id == pipeline and row.finished_at is not None


def test_agent_failure_is_recorded_not_raised(db):
    result = EchoAgent().run(EchoIn(items=["a"], fail=True), db)
    assert not result.ok and result.errors[0].code == "unhandled_exception"
    row = db.scalars(select(AgentRun).where(AgentRun.id == result.run_id)).one()
    assert row.status == RunStatus.failed and "boom" in row.errors[0]["message"]
    assert len(row.actions) == 1  # actions before the failure are kept for the audit trail


@pytest.mark.parametrize("raw", ['"abcd-1234".', "  abcd-1234\n", "'abcd-1234'", "“abcd-1234”,", "abcd-1234"])
def test_clean_secret(raw):
    assert crypto.clean_secret(raw) == "abcd-1234"
