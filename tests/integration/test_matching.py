import copy

import pytest
from sqlalchemy import func, select

from agents.job_agent.agents import run_job_scan
from agents.match_agent.agent import run_matching
from agents.match_agent.scoring import DISCLAIMER, LABEL
from agents.resume_agent.agent import DocumentInput, ResumeAnalyzerAgent, ResumeAnalyzerInput
from app.config import get_settings
from app.db.enums import Actor
from app.db.models import Job, JobMatch, JobSource
from app.schemas.settings import UserSettings
from app.services import settings_service
from tests.conftest import login
from tests.fixtures.jobs import FakeHttp, remotive_payload
from tests.fixtures.resumes import PRIMARY_TXT

REMOTIVE = "https://remotive.com/api/remote-jobs"


@pytest.fixture
def profile(db, owner, seeded, tmp_path, monkeypatch):
    """The fictional Ayesha Khan resume (about 4 years of dated DevOps experience) imported for the owner."""
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))
    path = tmp_path / "primary.txt"
    path.write_text(PRIMARY_TXT, encoding="utf-8")
    result = ResumeAnalyzerAgent().run(
        ResumeAnalyzerInput(user_id=owner.id, documents=[DocumentInput(path=str(path))]), db, user_id=owner.id
    )
    assert result.ok, result.errors
    src = db.scalars(select(JobSource).where(JobSource.key == "remotive")).one()
    src.enabled = True
    db.flush()


def _scan(db, owner, payload=None):
    return run_job_scan(
        db, owner.id, source_keys=["remotive"], http=FakeHttp({REMOTIVE: payload or remotive_payload()})
    )


def _match(db, owner, company):
    job = db.scalars(select(Job).where(Job.company == company)).one()
    return db.scalars(
        select(JobMatch).where(
            JobMatch.user_id == owner.id, JobMatch.job_id == job.id, JobMatch.job_content_version == job.content_version
        )
    ).one()


def test_scan_scores_every_target_job_with_explanations(db, owner, profile):
    result = _scan(db, owner)
    counts = result["matching"]["counts"]
    targets = db.scalar(select(func.count(Job.id)).where(Job.role_family.is_not(None)))
    assert counts["scored"] == targets and counts["created"] == targets
    assert result["matching"]["profile"]["tech_years"] > 4  # Jun 2022 - present, overlaps counted once

    northwind = _match(db, owner, "Northwind Cloud")  # Docker, Kubernetes, Terraform; worldwide; 2 years
    assert not northwind.knockouts
    assert northwind.breakdown["label"].startswith(f"{LABEL}: ")
    assert northwind.breakdown["disclaimer"] == DISCLAIMER
    assert northwind.evidence["kubernetes"]["credit"] >= 0.8 and northwind.evidence["kubernetes"]["fact_ids"]
    comps = northwind.breakdown["components"]
    assert sum(c["points"] for c in comps.values()) == pytest.approx(float(northwind.estimated_fit_score), abs=0.1)
    assert comps["location_remote"]["ratio"] == 1.0 and "Worldwide" in comps["location_remote"]["explanation"]

    usa = _match(db, owner, "Quantum Loop")
    assert [k["code"] for k in usa.knockouts] == ["pk_ineligible"] and "USA" in usa.knockouts[0]["reason"]
    assert usa.recommendation.startswith("Hidden: ")
    staff = _match(db, owner, "Monolith Inc")  # staff, 10 years, USA
    assert {"pk_ineligible", "seniority", "experience"} <= {k["code"] for k in staff.knockouts}

    for m in db.scalars(select(JobMatch)):
        assert "probability" not in m.breakdown["label"].lower()


def test_rescoring_updates_in_place_and_keeps_seen_state(db, owner, profile):
    _scan(db, owner)
    rows = db.scalar(select(func.count(JobMatch.id)))
    northwind = _match(db, owner, "Northwind Cloud")
    before = float(northwind.estimated_fit_score)

    s, _ = settings_service.get_effective(db, owner.id)
    heavy = s.model_dump()
    heavy["scoring_weights"] = {"skills": 60, "experience": 10, "github_evidence": 5, "education_certs": 5,
                                "role_seniority": 10, "location_remote": 5, "domain": 5}  # fmt: skip
    settings_service.save(db, owner.id, UserSettings.model_validate(heavy), actor=Actor.user)
    northwind.shown_to_user_at = northwind.created_at
    db.flush()

    out = run_matching(db, owner.id).output
    assert out["counts"].get("created", 0) == 0 and db.scalar(select(func.count(JobMatch.id))) == rows
    db.refresh(northwind)
    assert northwind.settings_version == out["settings_version"] > 1
    assert northwind.breakdown["previous_score"] == before
    assert northwind.breakdown["components"]["skills"]["max"] == 60
    assert northwind.shown_to_user_at is not None  # an unchanged job is never new again


def test_matches_api(client, db, owner, viewer, profile):
    _scan(db, owner)
    db.commit()
    h = login(client, owner)

    listed = client.get("/api/v1/matches", params={"min_score": 0}, headers=h).json()
    assert listed["label"] == LABEL and listed["disclaimer"] == DISCLAIMER
    scores = [m["estimated_fit_score"] for m in listed["matches"]]
    assert scores == sorted(scores, reverse=True) and listed["total"] > 0
    assert all(not m["knockouts"] and m["is_new"] for m in listed["matches"])
    everything = client.get("/api/v1/matches", params={"include_hidden": True, "limit": 500}, headers=h).json()
    assert everything["total"] > listed["total"]

    default = client.get("/api/v1/matches", headers=h).json()
    assert default["threshold"] == 80
    assert all(m["estimated_fit_score"] >= 80 for m in default["matches"])

    first = listed["matches"][0]
    detail = client.get(f"/api/v1/jobs/{first['job']['id']}/match", headers=h).json()
    assert set(detail["components"]) == {
        "skills", "experience", "github_evidence", "education_certs", "role_seniority", "location_remote", "domain"
    }  # fmt: skip
    assert detail["job"]["description"] and detail["evidence"]

    ids = [m["match_id"] for m in listed["matches"]]
    assert client.post("/api/v1/matches/seen", json={"match_ids": ids}, headers=h).status_code == 204
    assert client.get("/api/v1/matches", params={"min_score": 0, "new_only": True}, headers=h).json()["total"] == 0
    assert client.post("/api/v1/matches/run", headers=h).status_code == 200
    assert client.get("/api/v1/matches", params={"min_score": 0, "new_only": True}, headers=h).json()["total"] == 0

    # a material change (salary) creates a new job version, which is new again
    changed = copy.deepcopy(remotive_payload())
    changed["jobs"][0]["salary"] = "$65k - $85k"
    _scan(db, owner, changed)
    db.commit()
    fresh = client.get("/api/v1/matches", params={"min_score": 0, "new_only": True}, headers=h).json()
    assert [m["job"]["company"] for m in fresh["matches"]] == ["Northwind Cloud"]

    mid = fresh["matches"][0]["match_id"]
    assert client.post(f"/api/v1/matches/{mid}/dismiss", headers=h).status_code == 204
    after = client.get("/api/v1/matches", params={"min_score": 0}, headers=h).json()
    assert mid not in [m["match_id"] for m in after["matches"]]

    vh = login(client, viewer)
    assert client.post("/api/v1/matches/run", headers=vh).status_code == 403
    assert client.get("/api/v1/matches", headers=vh).json()["total"] == 0  # viewers never see the owner's matches
