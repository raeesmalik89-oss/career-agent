from tests.conftest import login
from tests.integration.test_matching import profile  # noqa: F401 - shared fixture

SUMMARY = "...Acme Pakistan is seeking a DevOps Engineer to own CI/CD pipelines and AWS infrastructure with Docker..."


def test_employer_link_replaces_job_board_links(client, db, owner, viewer, profile):  # noqa: F811
    db.commit()
    h = login(client, owner)
    body = {"title": "DevOps Engineer", "company": "Acme Pakistan", "description": SUMMARY,
            "url": "https://pk.jooble.org/away/123?p=1"}  # fmt: skip
    job = client.post("/api/v1/jobs/manual", headers=h, json=body).json()
    assert job["aggregator_link"] is True and job["employer_url"] is None

    path = f"/api/v1/jobs/{job['id']}/employer-link"
    assert client.put(path, json={"url": "http://acme.example.com/jobs/1"}, headers=h).status_code == 422  # not https
    bad = client.put(path, json={"url": "https://www.jobleads.com/register/pk/1"}, headers=h)
    assert bad.status_code == 422 and "job-board" in bad.json()["detail"]
    assert (
        client.put(path, json={"url": "https://acme.example.com/jobs/1"}, headers=login(client, viewer)).status_code
        == 403
    )

    ok = client.put(path, json={"url": "https://acme.example.com/careers/devops"}, headers=h).json()
    assert ok["employer_url"] == "https://acme.example.com/careers/devops" and ok["aggregator_link"] is False

    # an application prepared afterwards points at the employer, not the job board
    app = client.post("/api/v1/applications", json={"job_id": job["id"]}, headers=h)
    assert app.status_code == 201, app.text
    assert app.json()["application_url"] == "https://acme.example.com/careers/devops"

    cleared = client.put(path, json={"url": None}, headers=h).json()
    assert cleared["employer_url"] is None and cleared["aggregator_link"] is True
