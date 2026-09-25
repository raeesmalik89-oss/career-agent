"""AI suggestions for answers that need the user's input, with a fake provider."""

import json

import pytest

import agents.application_agent.ai_suggest as sug_mod
from app.db.enums import Actor
from app.schemas.settings import AiSettings, UserSettings
from app.services import settings_service
from tests.conftest import login
from tests.integration.test_ai_tailor import _prepare
from tests.integration.test_matching import profile  # noqa: F401 - shared fixture

CALLS: list[dict] = []


def fake_suggest(provider, *, model, api_key, system, user, **_opts):
    req = json.loads(user)
    CALLS.append({"system": system, "req": req})
    company = req["JOB POSTING"]["company"]
    if "expected salary" in system:
        options = [
            {"text": "PKR 90,000 - 110,000 per month (negotiable)", "why": "entry-level range in Islamabad"},
            {"text": "PKR 120,000 per month", "why": "market middle"},
            {"text": "PKR 150,000 per month", "why": "ambitious"},
        ]
    else:
        options = [
            {"text": f"{company}'s platform work matches my Kubernetes and Terraform training.", "why": "role fit"},
            {"text": "I want to grow on a team that runs Ansible at scale.", "why": "growth"},  # no evidence
            {"text": f"I like how openly {company} writes about its platform.", "why": "mission"},
        ]
    return {"options": options}, {"model": "fake-model"}


@pytest.fixture
def ai_on(db, owner, monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(sug_mod, "chat_json", fake_suggest)
    settings_service.save(db, owner.id, UserSettings(ai=AiSettings(provider="groq")), actor=Actor.system)
    db.commit()


def test_suggestions_are_checked_cached_and_picked(client, db, owner, profile, ai_on):  # noqa: F811
    h = login(client, owner)
    client.put("/api/v1/secrets", json={"name": "groq_api_key", "value": "gsk_fake_key_for_tests"}, headers=h)
    app = _prepare(client, db, owner, h)
    by_q = {a["question"]: a for a in app["answers"]}
    why = next(a for q, a in by_q.items() if q.startswith("Why do you want"))
    assert why["suggest"] == "motivation" and by_q["Expected salary"]["suggest"] == "salary"
    assert by_q["Email"]["suggest"] is None  # plain facts get no suggestions

    url = f"/api/v1/applications/{app['id']}/answers/{why['id']}/suggest"
    r = client.post(url, json={}, headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    # the Ansible option has no evidence: dropped; the rest kept, in order
    assert s["kind"] == "motivation" and s["dropped"] == 1 and len(s["options"]) == 2
    assert not any("Ansible" in o["text"] for o in s["options"]) and s["cached"] is False
    sent = json.dumps(CALLS[0]["req"])
    assert "ayesha.khan@example.com" not in sent and "+92-300" not in sent  # contact details never sent

    # cached: a second request costs no AI call, and the page gets them with the answer
    assert client.post(url, json={}, headers=h).json()["cached"] is True and len(CALLS) == 1
    detail = client.get(f"/api/v1/applications/{app['id']}", headers=h).json()
    assert next(a for a in detail["answers"] if a["id"] == why["id"])["suggestions"]["options"]
    client.post(url, json={"refresh": True}, headers=h)
    assert len(CALLS) == 2

    # salary: estimates, labelled as such
    sal = client.post(
        f"/api/v1/applications/{app['id']}/answers/{by_q['Expected salary']['id']}/suggest", json={}, headers=h
    ).json()
    assert sal["kind"] == "salary" and len(sal["options"]) == 3 and "out of date" in sal["note"]
    assert "technology_experience" in CALLS[-1]["req"]["CANDIDATE"]

    # picking one saves it as the user's answer, marked as an AI suggestion
    r = client.patch(
        f"/api/v1/applications/{app['id']}/answers/{why['id']}",
        json={"answer": s["options"][0]["text"], "ai_pick": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    picked = next(a for a in r.json()["answers"] if a["id"] == why["id"])
    assert picked["ai"] and picked["answer"] == s["options"][0]["text"]
    assert not any("Why" in b for b in r.json()["blockers"])

    # answers that come straight from your facts get no suggestions
    email = client.post(f"/api/v1/applications/{app['id']}/answers/{by_q['Email']['id']}/suggest", headers=h)
    assert email.status_code == 400


def test_suggestions_need_ai_turned_on(client, db, owner, profile):  # noqa: F811
    h = login(client, owner)
    app = _prepare(client, db, owner, h)
    why = next(a for a in app["answers"] if a["question"].startswith("Why do you want"))
    r = client.post(f"/api/v1/applications/{app['id']}/answers/{why['id']}/suggest", json={}, headers=h)
    assert r.status_code == 409 and "Settings" in r.json()["detail"]
