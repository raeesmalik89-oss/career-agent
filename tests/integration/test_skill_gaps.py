from agents.skill_agent.gaps import WEIGHTS, analyse
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture


def test_gap_statuses_and_priority(db, owner, profile):  # noqa: F811
    _scan(db, owner)
    report = analyse(db, owner.id, 30)
    assert report["jobs_analysed"] > 0 and WEIGHTS == report["weights"]
    gaps = {g["skill"]: g for g in report["gaps"]}
    # the fictional profile uses Kubernetes and Terraform in experience: have
    assert gaps["kubernetes"]["status"] == "have"
    # Python is needed by several mock jobs and is in the CV skills list: have or partial, never missing
    assert gaps["python"]["status"] in ("have", "partial")
    # LangChain / RAG are never mentioned in the fictional CV: missing, with the honest reason
    missing = [g for g in report["gaps"] if g["status"] == "missing"]
    assert missing and all(g["status_reason"] == "Evidence not found." for g in missing)
    for g in report["gaps"]:
        assert 0 <= g["priority"] <= 100 and g["jobs_requiring"] >= 2
    assert [g["priority"] for g in report["gaps"]] == sorted((g["priority"] for g in report["gaps"]), reverse=True)


def test_learning_flow_never_upgrades_skills(client, db, owner, viewer, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    resp = client.get("/api/v1/skills/gaps", params={"window": 30}, headers=h)
    assert resp.status_code == 200, resp.text
    gaps = resp.json()
    assert gaps["gaps"] and "guide" in gaps["gaps"][0]

    assert (
        client.post("/api/v1/learning/plan", json={"skills": ["gitops"]}, headers=login(client, viewer)).status_code
        == 403
    )
    r = client.post("/api/v1/learning/plan", json={"skills": ["gitops", "not_a_skill"]}, headers=h).json()
    assert r["created"] == 6  # six items for the one real skill with a guide
    again = client.post("/api/v1/learning/plan", json={"skills": ["gitops"]}, headers=h).json()
    assert again["created"] == 0  # idempotent

    guide = client.get("/api/v1/learning/skills/gitops", headers=h).json()
    assert guide["guide"]["curated"] and guide["concept_map"]["mermaid"].startswith("mindmap")
    before = guide["evidence"]["level"]
    for item in guide["items"]:
        r = client.patch(f"/api/v1/learning/items/{item['id']}", json={"status": "done"}, headers=h)
        assert r.status_code == 200 and r.json()["completed_at"]
    after = client.get("/api/v1/learning/skills/gitops", headers=h).json()["evidence"]
    assert after["level"] == before  # studying alone never changes the level
    listed = client.get("/api/v1/learning", headers=h).json()["skills"]
    assert listed[0]["done"] == listed[0]["total"] == 6

    fallback = client.get("/api/v1/learning/skills/cobol", headers=h)
    assert fallback.status_code == 404
    plain = client.get("/api/v1/learning/skills/rabbitmq", headers=h).json()
    assert plain["guide"]["curated"] is False and plain["concept_map"] is None
