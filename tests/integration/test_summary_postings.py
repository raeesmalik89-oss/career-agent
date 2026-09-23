"""A summary-only posting (e.g. Jooble's teaser) is never shown as a match until its full text is known."""

from tests.conftest import login
from tests.fixtures.jobs import INTRO
from tests.integration.test_matching import profile  # noqa: F401 - shared fixture

SUMMARY = (
    "...Northwind Pakistan is seeking a DevOps Engineer to own CI/CD pipelines and AWS infrastructure with Docker..."
)
FULL = (
    INTRO + "\n\nRequirements:\n- 10+ years of experience with Docker, Kubernetes and Terraform on AWS.\n"
    "- Own on-call and incident response.\n\nBenefits:\n- Laptop"
)


def _add(client, h, description, **extra):
    body = {"title": "DevOps Engineer", "company": "Northwind Pakistan", "location": "Islamabad",
            "remote": "onsite", "description": description, **extra}  # fmt: skip
    r = client.post("/api/v1/jobs/manual", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_summary_is_unconfirmed_until_the_full_posting_takes_over(client, db, owner, profile):  # noqa: F811
    db.commit()
    h = login(client, owner)
    job = _add(client, h, SUMMARY)
    assert job["summary_only"] is True and job["content_version"] == 1
    m = client.get(f"/api/v1/jobs/{job['id']}/match", headers=h).json()
    assert [k["code"] for k in m["knockouts"]] == ["unconfirmed"]
    assert "summary" in m["knockouts"][0]["reason"] and m["recommendation"].startswith("Hidden: ")
    shown = client.get("/api/v1/matches", params={"min_score": 0}, headers=h).json()
    assert job["id"] not in [x["job"]["id"] for x in shown["matches"]]

    # the user pastes the full posting for that job (its title on the company site may differ)
    full = _add(client, h, FULL, job_id=job["id"], url="https://careers.example.com/devops")
    assert full["id"] == job["id"] and full["summary_only"] is False and full["content_version"] == 2
    assert full["experience_required_years"] == 10
    m2 = client.get(f"/api/v1/jobs/{job['id']}/match", headers=h).json()
    codes = [k["code"] for k in m2["knockouts"]]
    assert "unconfirmed" not in codes and "experience" in codes  # the real requirement is now visible

    # the summary arriving again does not take the job back
    again = _add(client, h, SUMMARY)
    assert again["id"] == job["id"] and again["summary_only"] is False and again["content_version"] == 2


def test_full_text_for_unknown_job_is_404(client, owner):
    h = login(client, owner)
    r = client.post(
        "/api/v1/jobs/manual",
        headers=h,
        json={
            "title": "Some role",
            "company": "Y",
            "description": FULL,
            "job_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 404
