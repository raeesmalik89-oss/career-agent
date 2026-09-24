import copy

import pytest
from sqlalchemy import select

from agents.job_agent.agents import run_job_scan
from app.db.models import Job, JobSource, JobSourceLink, Secret
from integrations.sources.base import SourceError
from integrations.sources.connectors import Greenhouse, Jooble, WeWorkRemotely
from tests.conftest import login
from tests.fixtures.jobs import MOCK_SPECS, FakeHttp, himalayas_payload, remotive_payload

REMOTIVE = "https://remotive.com/api/remote-jobs"
HIMALAYAS = "https://himalayas.app/jobs/api/search"


@pytest.fixture
def sources(db, seeded):
    for src in db.scalars(select(JobSource).where(JobSource.key.in_(["remotive", "himalayas"]))):
        src.enabled = True
    db.flush()


def _scan(db, user, routes, keys=("remotive", "himalayas")):
    return run_job_scan(db, user.id, source_keys=list(keys), http=FakeHttp(routes))


def test_scan_meets_minimum_dedups_and_classifies(db, owner, sources):
    routes = {REMOTIVE: remotive_payload(), HIMALAYAS: himalayas_payload(MOCK_SPECS[:5])}
    result = _scan(db, owner, routes)
    d = result["discovery"]
    assert d["met_minimum"] and d["scanned"] >= 30 and d["skipped_stale"] >= 1  # the 120-day-old role is dropped
    statuses = result["ingest"]["statuses"]
    assert statuses["duplicate"] == 5  # the same 5 vacancies also appear on Himalayas
    northwind = db.scalars(select(Job).where(Job.company == "Northwind Cloud")).one()
    links = db.scalars(select(JobSourceLink).where(JobSourceLink.job_id == northwind.id)).all()
    assert len(links) == 2
    assert northwind.role_family == "devops" and northwind.pk_eligibility.value == "eligible"
    assert float(northwind.salary_min) == 60000 and northwind.salary_currency == "USD"
    assert northwind.experience_required_years == 2
    assert db.scalars(select(Job).where(Job.company == "Pixel Corp")).first() is None  # not a target search
    usa = db.scalars(select(Job).where(Job.company == "Quantum Loop")).one()
    assert usa.pk_eligibility.value == "ineligible" and "USA" in usa.pk_eligibility_evidence


def test_rescan_is_stable_and_material_changes_bump_version(db, owner, sources):
    routes = {REMOTIVE: remotive_payload()}
    _scan(db, owner, routes, keys=("remotive",))
    again = _scan(db, owner, routes, keys=("remotive",))
    assert set(again["ingest"]["statuses"]) == {"unchanged"}

    changed = copy.deepcopy(routes[REMOTIVE])
    changed["jobs"][0]["salary"] = "$65k - $85k"  # material: salary
    changed["jobs"][1]["description"] += "<p>We also have a nice office dog.</p>"  # not material
    result = _scan(db, owner, {REMOTIVE: changed}, keys=("remotive",))
    assert result["ingest"]["statuses"]["changed"] == 1
    northwind = db.scalars(select(Job).where(Job.company == "Northwind Cloud")).one()
    assert northwind.content_version == 2 and float(northwind.salary_min) == 65000
    blue = db.scalars(select(Job).where(Job.company == "Blue Harbor")).one()
    assert blue.content_version == 1


def test_eligible_variant_upgrades_job(db, owner, sources):
    spec = ("SRE", "Variant Co", "USA", "Kubernetes", "Helm", 3, "", 1)
    us = remotive_payload([spec])
    world = remotive_payload([spec[:2] + ("Worldwide",) + spec[3:]])
    world["jobs"][0]["id"] = 99_999  # same vacancy, another location variant
    _scan(db, owner, {REMOTIVE: {"jobs": us["jobs"] + world["jobs"]}}, keys=("remotive",))
    job = db.scalars(select(Job).where(Job.company == "Variant Co")).one()
    assert job.pk_eligibility.value == "eligible" and "Worldwide" in job.pk_eligibility_evidence


def test_below_minimum_widens_and_warns(db, owner, sources):
    result = _scan(db, owner, {REMOTIVE: remotive_payload(MOCK_SPECS[:3])}, keys=("remotive",))
    d = result["discovery"]
    assert d["widened"] and not d["met_minimum"] and d["scanned"] == 3


def test_failing_source_is_recorded_and_others_continue(db, owner, sources):
    result = _scan(
        db, owner, {REMOTIVE: SourceError("HTTP 503 from remotive.com"), HIMALAYAS: himalayas_payload(MOCK_SPECS[:4])}
    )
    assert result["discovery"]["scanned"] == 4
    assert result["errors"][0]["code"] == "source_failed" and "remotive" in result["errors"][0]["message"]


# ------------------------------------------------------------------ connectors


def test_greenhouse_skips_bad_boards():
    http = FakeHttp(
        {
            "https://boards-api.greenhouse.io/v1/boards/good/": {
                "jobs": [
                    {
                        "id": 1,
                        "title": "Site Reliability Engineer",
                        "company_name": "Good",
                        "absolute_url": "https://g/1",
                        "content": "&lt;p&gt;Remote, worldwide&lt;/p&gt;",
                        "location": {"name": "Remote"},
                    }
                ]
            }
        }
    )
    out = Greenhouse(http, {"companies": ["missing", "good"]}).fetch(["site reliability"], 10)
    assert [p.title for p in out] == ["Site Reliability Engineer"] and out[0].description == "Remote, worldwide"


def test_wwr_rss():
    rss = """<?xml version="1.0"?><rss><channel><item><title>Acme: DevOps Engineer</title>
      <region>Anywhere in the World</region><link>https://weworkremotely.com/x</link><guid>g1</guid>
      <description>&lt;p&gt;Kubernetes&lt;/p&gt;</description><pubDate>Mon, 21 Sep 2026 10:00:00 +0000</pubDate>
      <type>Full-Time</type></item></channel></rss>"""
    out = WeWorkRemotely(FakeHttp({"https://weworkremotely.com/": rss}), {"categories": ["x"]}).fetch(["devops"], 5)
    assert out[0].company == "Acme" and out[0].title == "DevOps Engineer"
    assert out[0].location_restrictions == ["Anywhere in the World"] and out[0].posted_at.year == 2026


def test_jooble_requires_key():
    with pytest.raises(SourceError, match="API key"):
        Jooble(FakeHttp({}), {}).fetch(["devops"], 5)


def test_jooble_uses_few_requests_and_respects_quota():
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "DevOps Engineer",
                "company": "Isb Co",
                "link": "https://jooble.org/x",
                "snippet": "Docker",
                "location": "Islamabad",
                "updated": "2026-09-20T00:00:00",
            }
        ]
    }
    http = FakeHttp({"https://jooble.org/api/": payload})
    j = Jooble(http, {"api_key": "abcd-1234-efgh-5678"})
    out = j.fetch(["devops engineer", "sre", "mlops", "cloud engineer", "ai engineer"], 50)
    assert j.requests_made == 4 and len(http.calls) == 4 and out[0].location == "Islamabad"
    limited = Jooble(
        FakeHttp({"https://jooble.org/api/": payload}),
        {"api_key": "abcd-1234-efgh-5678", "quota": 500, "requests_used": 498},
    )
    limited.fetch(["devops"], 50)
    assert limited.requests_made == 2
    with pytest.raises(SourceError, match="quota"):
        Jooble(FakeHttp({}), {"api_key": "abcd-1234-efgh-5678", "requests_used": 500}).fetch(["devops"], 5)


# ------------------------------------------------------------------ API


def test_jobs_api(client, db, owner, viewer, sources, monkeypatch):
    import agents.job_agent.agents as agents_mod

    routes = {REMOTIVE: remotive_payload(), HIMALAYAS: himalayas_payload([])}
    original = agents_mod.HttpClient
    monkeypatch.setattr(agents_mod, "HttpClient", lambda hosts: FakeHttp(routes))
    headers = login(client, owner)
    assert client.post("/api/v1/jobs/scan", headers=login(client, viewer), json={}).status_code == 403
    r = client.post("/api/v1/jobs/scan", headers=headers, json={"source_keys": ["remotive"]})
    assert r.status_code == 200 and r.json()["discovery"]["scanned"] >= 30, r.text
    monkeypatch.setattr(agents_mod, "HttpClient", original)

    listing = client.get("/api/v1/jobs?pk=eligible&family=devops", headers=headers).json()
    assert listing["total"] >= 3 and all(j["pk_eligibility"] == "eligible" for j in listing["jobs"])
    detail = client.get(f"/api/v1/jobs/{listing['jobs'][0]['id']}", headers=headers).json()
    assert detail["skills"] and detail["sources"] and detail["pk_eligibility_evidence"]

    manual = client.post(
        "/api/v1/jobs/manual",
        headers=headers,
        json={
            "title": "DevOps Engineer",
            "company": "Islamabad Tech",
            "location": "Islamabad, Pakistan",
            "remote": "onsite",
            "description": "Requirements: 2+ years of experience with Docker and Kubernetes on AWS.",
        },
    )
    body = manual.json()
    assert manual.status_code == 201 and body["pk_eligibility"] == "eligible" and body["sources"][0][0] == "manual"
    stats = client.get("/api/v1/jobs-stats", headers=headers).json()
    assert stats["target_jobs"] >= 25


def test_secrets_are_encrypted_and_never_returned(client, db, owner):
    headers = login(client, owner)
    r = client.put("/api/v1/secrets", headers=headers, json={"name": "jooble_api_key", "value": "abcd-1234-efgh"})
    assert r.status_code == 204 and r.content == b""
    row = db.scalars(select(Secret).where(Secret.name == "jooble_api_key")).one()
    assert b"abcd-1234-efgh" not in row.ciphertext
    assert client.put("/api/v1/secrets", headers=headers, json={"name": "other", "value": "x" * 8}).status_code == 422


def test_widening_never_spends_metered_quota(db, owner, sources):
    from app.core import crypto

    jooble = db.scalars(select(JobSource).where(JobSource.key == "jooble")).one()
    jooble.enabled = True
    db.add(
        Secret(
            user_id=owner.id,
            name="jooble_api_key",
            key_version=1,
            ciphertext=crypto.encrypt("abcd-1234-efgh-5678", b"jooble_api_key"),
        )
    )
    db.flush()
    http = FakeHttp({"https://jooble.org/api/": {"jobs": []}, REMOTIVE: remotive_payload(MOCK_SPECS[:2])})
    result = run_job_scan(db, owner.id, source_keys=["remotive", "jooble"], http=http)
    assert result["discovery"]["widened"]
    assert sum("jooble.org" in c for c in http.calls) == 4  # one pass only, not repeated when widening
    assert jooble.config["requests_used"] == 4


def test_jooble_rotates_searches_across_scans():
    """Each scan spends only 4 requests, but successive scans cover the whole list (entry-level searches too)."""
    config = {"api_key": "abcd-1234-efgh-5678"}
    seen = []
    for _ in range(3):
        http = FakeHttp({"https://jooble.org/api/": {"jobs": []}})
        j = Jooble(http, config)
        j.fetch(["devops"], 5)
        assert j.requests_made == 4
        seen += [(p["keywords"], p["location"]) for p in http.posted]
        config = {**config, **j.state}
    n = len(Jooble.DEFAULT_SEARCHES)
    assert config["search_cursor"] == 12 % n
    assert len(seen) == 12 and set(seen) == set(Jooble.DEFAULT_SEARCHES)  # every search, incl. entry-level
    assert ("junior devops", "Pakistan") in seen


def test_jooble_country_host():
    payload = {"jobs": []}
    http = FakeHttp({"https://pk.jooble.org/api/": payload})
    Jooble(http, {"api_key": "abcd-1234-efgh-5678", "api_host": "pk.jooble.org"}).fetch(["devops"], 5)
    assert http.calls[0].startswith("https://pk.jooble.org/api/")
    with pytest.raises(SourceError, match="unsupported"):
        Jooble(FakeHttp({}), {"api_key": "abcd-1234-efgh-5678", "api_host": "evil.example.com"}).fetch(["x"], 5)
