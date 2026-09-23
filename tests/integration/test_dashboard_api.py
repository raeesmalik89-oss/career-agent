from sqlalchemy import select

from app.db.enums import Confidence, FactType, ReviewStatus, SourceType
from app.db.models import ProfileFact, Skill, UserSkill
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture


def test_dashboard_summary(client, db, owner, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    d = client.get("/api/v1/dashboard", headers=h).json()
    assert d["label"] == "Estimated Resume-to-Job Fit Score" and "not a probability" in d["disclaimer"]
    assert d["jobs"]["scanned_today"] >= 30 and d["jobs"]["daily_minimum"] == 30
    assert sum(d["matches"].values()) - d["matches"]["new"] == d["jobs"]["targets"]
    assert d["facts"]["pending"] > 0 and d["facts"]["verified"] == 0
    assert [r["agent"] for r in d["recent_runs"]][:3] == ["job_matcher", "job_ingest", "job_discovery"]


def test_bulk_verify_skips_conflicts_and_rejected(client, db, owner, profile):  # noqa: F811
    pending = db.scalars(
        select(ProfileFact).where(ProfileFact.user_id == owner.id, ProfileFact.review_status == ReviewStatus.pending)
    ).all()[:3]
    conflicted = ProfileFact(
        user_id=owner.id, fact_type=FactType.experience, fact_key="experience:x|2020",
        data={"title": "A", "conflicts": [{"field": "title", "values": ["A", "B"]}]},
        source_type=SourceType.resume, source_ref={"sources": []}, confidence=Confidence.medium,
    )  # fmt: skip
    pending[2].review_status = ReviewStatus.rejected
    db.add(conflicted)
    db.commit()
    h = login(client, owner)
    ids = [str(f.id) for f in (*pending, conflicted)]
    r = client.post("/api/v1/profile/facts/verify-bulk", json={"fact_ids": ids}, headers=h).json()
    assert r["verified"] == ids[:2]
    assert {s["reason"] for s in r["skipped"]} == {"resolve conflicts first", "rejected; restore it first"}
    assert client.get("/api/v1/dashboard", headers=h).json()["facts"]["verified"] == 2

    vh = login(client, _viewer(db))
    assert client.post("/api/v1/profile/facts/verify-bulk", json={"fact_ids": ids}, headers=vh).status_code == 403


def _viewer(db):
    from app.db.enums import Role
    from tests.conftest import make_user

    return make_user(db, Role.viewer)


def test_rejecting_a_skill_claim_removes_the_skill(client, db, owner, profile):  # noqa: F811
    claim = db.scalars(
        select(ProfileFact).where(
            ProfileFact.user_id == owner.id,
            ProfileFact.fact_type == FactType.skill_claim,
            ProfileFact.fact_key == "datadog",
        )
    ).one()
    datadog = db.scalars(select(Skill).where(Skill.canonical_name == "datadog")).one()
    has = lambda: db.scalars(  # noqa: E731
        select(UserSkill).where(UserSkill.user_id == owner.id, UserSkill.skill_id == datadog.id)
    ).first()
    assert has() is not None
    h = login(client, owner)
    r = client.patch(f"/api/v1/profile/facts/{claim.id}", json={"review_status": "rejected"}, headers=h)
    assert r.status_code == 200
    db.expire_all()
    assert has() is None
