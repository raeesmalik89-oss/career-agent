import io

from docx import Document
from sqlalchemy import select

from app.db.models import Job
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture


def _job(db, company):
    return db.scalars(select(Job).where(Job.company == company)).one()


def _answers(detail):
    return {a["question"]: a for a in detail["answers"]}


def test_application_lifecycle(client, db, owner, viewer, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    job = _job(db, "Northwind Cloud")

    assert (
        client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=login(client, viewer)).status_code
        == 403
    )
    r = client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=h)
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["status"] == "pending_approval" and app["mode"] == "assisted"

    # nothing in the tailored resume is unsupported by the facts
    assert app["resume_validation"]["counts"]["unsupported"] == 0
    skills = [s["text"] for g in app["resume"]["skills"] for s in g["items"]]
    assert "Kubernetes" in skills and "Terraform" in skills
    assert app["resume"]["skills"][0]["group"] == "Relevant to this role"
    assert "Ansible" not in skills  # never listed without evidence

    trace = {t["rule"]: t["passed"] for t in app["policy"]["submission"]["trace"]}
    assert app["policy"]["submission"]["outcome"] == "pending_approval" and trace["auto_apply_enabled"] is False

    answers = _answers(app)
    assert (
        answers["Cover letter"]["category"] == "open_ended"
        and "[Why Northwind Cloud" in answers["Cover letter"]["answer"]
    )
    assert answers["Email"]["answer"] == "ayesha.khan@example.com" and answers["Email"]["category"] == "factual"
    assert answers["Years of relevant experience"]["answer"].startswith("4.")
    assert any("[bracketed]" in b for b in app["blockers"])

    # a second application for the same job is refused and points at the first
    dup = client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=h)
    assert dup.status_code == 409 and dup.json()["existing_id"] == app["id"]

    # approval is blocked until the placeholders are replaced
    assert client.post(f"/api/v1/applications/{app['id']}/approve", headers=h).status_code == 422

    letter = answers["Cover letter"]["answer"].replace(
        "[Why Northwind Cloud: write one or two sentences in your own words.]",
        "I like how Northwind Cloud writes openly about its infrastructure.",
    )
    for q, text in (
        ("Cover letter", letter),
        ("Why do you want to work at Northwind Cloud?", "Your public engineering blog."),
        ("Expected salary", ""),  # this form does not ask: cleared, so not used
    ):
        r = client.patch(
            f"/api/v1/applications/{app['id']}/answers/{answers[q]['id']}", json={"answer": text}, headers=h
        )
        assert r.status_code == 200, r.text

    # a user-written claim about a technology with no evidence is flagged for the user's attention
    why = _answers(r.json())["Why do you want to work at Northwind Cloud?"]["id"]
    flagged = client.patch(
        f"/api/v1/applications/{app['id']}/answers/{why}", json={"answer": "I love Ansible."}, headers=h
    ).json()
    assert any(
        "Ansible" in n for n in _answers(flagged)["Why do you want to work at Northwind Cloud?"]["validation_notes"]
    )
    client.patch(f"/api/v1/applications/{app['id']}/answers/{why}", json={"answer": "Your blog."}, headers=h)

    ok = client.post(f"/api/v1/applications/{app['id']}/approve", headers=h)
    assert ok.status_code == 200, ok.text
    detail = ok.json()
    assert detail["status"] == "awaiting_manual_submit" and all(a["approved"] for a in detail["answers"])
    assert [e["type"] for e in detail["events"]][-2:] == ["approved", "awaiting_manual_submit"]

    # downloads are real DOCX files
    doc = Document(io.BytesIO(client.get(f"/api/v1/applications/{app['id']}/resume.docx", headers=h).content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Ayesha Khan" in text and "EXPERIENCE" in text and "Kubernetes" in text
    cl = client.get(f"/api/v1/applications/{app['id']}/cover-letter.docx", headers=h)
    assert "openly about its infrastructure" in "\n".join(p.text for p in Document(io.BytesIO(cl.content)).paragraphs)

    # after submitting on the employer's site, the user tracks progress
    assert (
        client.post(f"/api/v1/applications/{app['id']}/status", json={"status": "offer"}, headers=h).status_code == 409
    )
    applied = client.post(f"/api/v1/applications/{app['id']}/status", json={"status": "applied"}, headers=h).json()
    assert applied["status"] == "applied" and applied["submitted_at"]
    assert client.post(f"/api/v1/applications/{app['id']}/answers/x", headers=h).status_code in (404, 405)
    assert client.post(f"/api/v1/applications/{app['id']}/reject", json={}, headers=h).status_code == 409

    listed = client.get("/api/v1/applications", headers=h).json()
    assert [a["status"] for a in listed] == ["applied"]
    assert client.get("/api/v1/applications", headers=login(client, viewer)).json() == []


def test_repost_counts_as_duplicate(client, db, owner, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    job = _job(db, "Northwind Cloud")
    first = client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=h).json()
    repost = Job(
        fingerprint="x" * 64, title="DevOps Engineer", company="Northwind Cloud",
        company_normalized=job.company_normalized, url="https://example.com/repost", description=job.description,
        description_hash="y" * 64,
    )  # fmt: skip
    db.add(repost)
    db.commit()
    r = client.post("/api/v1/applications", json={"job_id": str(repost.id)}, headers=h)
    assert r.status_code == 409 and r.json()["existing_id"] == first["id"]


def test_withdraw_and_rebuild(client, db, owner, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    app = client.post("/api/v1/applications", json={"job_id": str(_job(db, "Blue Harbor").id)}, headers=h).json()
    rebuilt = client.post(f"/api/v1/applications/{app['id']}/rebuild", headers=h)
    assert rebuilt.status_code == 200 and rebuilt.json()["resume"] is not None
    gone = client.post(f"/api/v1/applications/{app['id']}/reject", json={"reason": "not for me"}, headers=h).json()
    assert gone["status"] == "withdrawn"
    assert client.post(f"/api/v1/applications/{app['id']}/rebuild", headers=h).status_code == 409
