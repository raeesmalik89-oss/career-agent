import pytest
from sqlalchemy import select

from agents.resume_agent.agent import DocumentInput, ResumeAnalyzerAgent, ResumeAnalyzerInput
from agents.resume_agent.report import experience_summary
from app.db.enums import ReviewStatus, SkillLevel
from app.db.models import AuditLog, ProfileFact, ResumeVersion, Skill, UserSkill
from tests.conftest import login
from tests.fixtures.resumes import CERTIFICATE_TXT, PRIMARY_TXT, SECONDARY_TXT, docx_bytes


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))


def _write(tmp_path, name: str, data: bytes | str) -> str:
    p = tmp_path / name
    p.write_bytes(data.encode() if isinstance(data, str) else data)
    return str(p)


def _import(db, user, tmp_path, *files):
    docs = [DocumentInput(path=_write(tmp_path, n, d)) for n, d in files]
    return ResumeAnalyzerAgent().run(ResumeAnalyzerInput(user_id=user.id, documents=docs), db, user_id=user.id)


def _facts(db, user, ftype):
    return list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == user.id, ProfileFact.fact_type == ftype)))


def test_import_merges_versions_and_records_conflicts(db, owner, tmp_path):
    result = _import(db, owner, tmp_path, ("primary.txt", PRIMARY_TXT), ("secondary.docx", docx_bytes(SECONDARY_TXT)),
                     ("cert.txt", CERTIFICATE_TXT))  # fmt: skip
    assert result.ok, result.errors
    versions = list(db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == owner.id)))
    assert sorted(v.kind.value for v in versions) == ["certificate", "source", "source"]

    exp = {f.data["organization"]: f for f in _facts(db, owner, "experience")}
    acme = exp["Acme Cloud Ltd"]
    assert len(acme.source_ref["sources"]) == 2  # same job from both resumes merged into one fact
    assert acme.data["conflicts"][0]["field"] == "title"  # Engineer vs Senior Engineer
    assert acme.confidence.value == "low" and acme.review_status == ReviewStatus.pending
    src = acme.source_ref["sources"][0]
    assert src["label"] == "primary" and "DevOps Engineer" in src["snippet"]

    edu = _facts(db, owner, "education")
    assert len(edu) == 1 and len(edu[0].source_ref["sources"]) == 2

    certs = {f.data["name"] for f in _facts(db, owner, "certification")}
    assert {"Certificate in DevOps and Cloud", "AWS Certified Cloud Practitioner (2023)"} <= certs

    report = result.output
    assert report["profile"]["name"] == "Ayesha Khan"
    assert report["experience_summary"]["tech_months_training"] == 7
    assert any("Job titles differ" in r for r in report["recommendations"])
    assert {"fact_id", "conflicts"} <= report["conflicts"][0].keys()


def test_user_skill_levels_come_from_evidence(db, owner, tmp_path):
    _import(db, owner, tmp_path, ("primary.txt", PRIMARY_TXT))
    rows = db.execute(
        select(UserSkill, Skill).join(Skill, Skill.id == UserSkill.skill_id).where(UserSkill.user_id == owner.id)
    )
    levels = {s.canonical_name: us.level for us, s in rows}
    assert levels["kubernetes"] == SkillLevel.working  # used in experience
    assert levels["datadog"] == SkillLevel.exposure  # only listed
    assert SkillLevel.strong not in levels.values()  # never assigned from a resume alone


def test_reimport_same_file_is_skipped(db, owner, tmp_path):
    _import(db, owner, tmp_path, ("primary.txt", PRIMARY_TXT))
    count = len(list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == owner.id))))
    again = _import(db, owner, tmp_path, ("primary.txt", PRIMARY_TXT))
    assert [a.type for a in again.actions] == ["skip_already_analyzed"]
    assert len(list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == owner.id)))) == count


def test_unreadable_file_is_reported_not_raised(db, owner, tmp_path):
    result = _import(db, owner, tmp_path, ("broken.pdf", b"garbage"))
    assert not result.ok and result.errors[0].code == "document_unreadable"


def test_experience_summary_counts_overlaps_once():
    class F:
        def __init__(self, **d):
            self.data = d

    facts = [F(start="2020", end="2024", sector="healthcare"), F(start="2021-01", end="2022-12", sector="healthcare"),
             F(start="2024-08", end="2025-08", sector="tech", is_training=True)]  # fmt: skip
    s = experience_summary(facts)
    assert s["healthcare_months"] == 60 and s["tech_months_training"] == 13 and s["tech_months_professional"] == 0


# ------------------------------------------------------------------ API


def test_upload_api_and_fact_review(client, db, owner):
    headers = login(client, owner)
    files = [("files", ("primary.txt", PRIMARY_TXT.encode(), "text/plain")),
             ("files", ("secondary.docx", docx_bytes(SECONDARY_TXT), "application/octet-stream"))]  # fmt: skip
    r = client.post("/api/v1/resume/upload", headers=headers, files=files)
    assert r.status_code == 200 and r.json()["ok"], r.text

    versions = client.get("/api/v1/resume/versions", headers=headers).json()
    assert [v["filename"] for v in versions] == ["primary.txt", "secondary.docx"]

    report = client.get("/api/v1/resume/intelligence", headers=headers).json()
    assert report["review"]["pending"] > 0 and report["conflicts"]

    conflicted = report["conflicts"][0]["fact_id"]
    assert client.post(f"/api/v1/profile/facts/{conflicted}/verify", headers=headers).status_code == 409

    fact = client.get("/api/v1/profile/facts?fact_type=experience", headers=headers).json()
    target = next(f for f in fact if f["id"] == conflicted)
    fixed = {**target["data"], "title": "DevOps Engineer"}
    fixed.pop("conflicts")
    r = client.patch(f"/api/v1/profile/facts/{conflicted}", headers=headers,
                     json={"data": fixed, "resolve_conflicts": True, "note": "Engineer is correct"})  # fmt: skip
    body = r.json()
    assert r.status_code == 200 and body["review_status"] == "verified" and "conflicts" not in body["data"]
    assert body["source_ref"]["sources"][-1]["entered_by"] == "user"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "fact.update")).one()
    assert entry.reason == "Engineer is correct"

    skill = next(f for f in client.get("/api/v1/profile/facts?fact_type=skill_claim", headers=headers).json()
                 if f["fact_key"] == "datadog")  # fmt: skip
    r = client.patch(f"/api/v1/profile/facts/{skill['id']}", headers=headers, json={"review_status": "rejected"})
    assert r.json()["review_status"] == "rejected"
    report = client.get("/api/v1/resume/intelligence", headers=headers).json()
    all_skills = {s["skill"] for items in report["skills_by_category"].values() for s in items}
    assert "datadog" not in all_skills  # rejected facts disappear from the report


def test_manual_fact_is_verified(client, owner):
    headers = login(client, owner)
    r = client.post("/api/v1/profile/facts", headers=headers,
                    json={"fact_type": "certification", "data": {"name": "CKA", "issued": "2026-05"}})  # fmt: skip
    assert r.status_code == 201
    assert r.json()["review_status"] == "verified" and r.json()["source_type"] == "manual"


def test_upload_rejections(client, owner, viewer):
    headers = login(client, owner)
    r = client.post("/api/v1/resume/upload", headers=headers, files=[("files", ("x.exe", b"MZ", "application/x"))])
    assert r.status_code == 415
    vh = login(client, viewer)
    r = client.post("/api/v1/resume/upload", headers=vh, files=[("files", ("a.txt", b"hi", "text/plain"))])
    assert r.status_code == 403


def test_facts_are_private_to_their_owner(client, db, owner, tmp_path):
    from tests.conftest import make_user

    _import(db, owner, tmp_path, ("primary.txt", PRIMARY_TXT))
    db.commit()
    fact_id = _facts(db, owner, "experience")[0].id
    other = make_user(db)
    r = client.post(f"/api/v1/profile/facts/{fact_id}/verify", headers=login(client, other))
    assert r.status_code == 404
