"""AI tailoring with a fake provider: nothing leaves the test, and the validator stays in charge."""

import json

import pytest
from sqlalchemy import select

import agents.application_agent.ai_tailor as ai_mod
from app.db.enums import Actor
from app.db.models import Job
from app.schemas.settings import AiSettings, UserSettings
from app.services import settings_service
from integrations.llm import PROVIDERS, LLMError, endpoint, parse_json
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture

SENT: list[dict] = []


def fake_ai(provider, *, model, api_key, system, user, ollama_url=None, temperature=0.3, **_opts):
    """Rewrites every bullet; invents Ansible in the first one and a percentage in one letter paragraph."""
    req = json.loads(user)
    SENT.append(req)
    bullets = []
    for i, u in enumerate(req["units"]):
        text = f"Delivered: {u['text']}"
        if i == 0:
            text += " using Ansible"  # a technology with no evidence: must be rejected
        bullets.append({"id": u["id"], "text": text})
    return (
        {
            "summary": "DevOps engineer focused on Kubernetes and Terraform automation.",
            "bullets": bullets,
            "cover_letter": [
                f"I am applying for the {req['job']['title']} role at {req['job']['company']}.",
                "I cut deployment time by 97% across every team.",  # invented number: must be rejected
                "I would bring careful automation and clear documentation.",
            ],
            "why_company": f"I like how openly {req['job']['company']} writes about its platform.",
        },
        {"prompt_tokens": 1000, "completion_tokens": 400},
    )


@pytest.fixture
def ai_on(db, owner, monkeypatch):
    SENT.clear()
    monkeypatch.setattr(ai_mod, "chat_json", fake_ai)
    s = UserSettings(ai=AiSettings(provider="groq"))
    settings_service.save(db, owner.id, s, actor=Actor.system)
    db.commit()


def _prepare(client, db, owner, h):
    _scan(db, owner)
    db.commit()
    job = db.scalars(select(Job).where(Job.company == "Northwind Cloud")).one()
    r = client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_ai_rewrites_but_validator_keeps_the_truth(client, db, owner, profile, ai_on):  # noqa: F811
    h = login(client, owner)
    client.put("/api/v1/secrets", json={"name": "groq_api_key", "value": "gsk_fake_key_for_tests"}, headers=h)
    app = _prepare(client, db, owner, h)
    r = client.post(f"/api/v1/applications/{app['id']}/ai-tailor", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    report = d["ai"]
    assert report["provider"] == "groq" and report["lines_rewritten"] >= 2

    # the first bullet claimed Ansible: rejected, original kept, reason reported
    rejected = {k["part"]: k for k in report["kept_original"]}
    first = next(p for p in rejected if p.endswith("bullets.0"))
    assert "Ansible" in rejected[first]["ai_text"] and any("Ansible" in n for n in rejected[first]["reason"])
    bullets = [b for e in d["resume"]["experience"] for b in e["bullets"]] + [
        b for p in d["resume"]["projects"] for b in p["bullets"]
    ]
    assert not any("Ansible" in b["text"] for b in bullets)
    assert any(b.get("ai") and b["text"].startswith("Delivered:") and b["original"] for b in bullets)
    assert d["resume"]["summary"]["ai"] is True
    assert d["resume_validation"]["counts"]["unsupported"] == 0  # nothing unsupported reached the resume

    # cover letter: the invented 97% paragraph is dropped, the rest used; "why" drafted from the posting
    letter = next(a for a in d["answers"] if a["question"] == "Cover letter")
    assert "97%" not in letter["answer"] and "careful automation" in letter["answer"] and letter["ai"]
    assert any(k["part"].startswith("cover letter") for k in report["kept_original"])
    why = next(a for a in d["answers"] if a["question"].startswith("Why do you want"))
    assert why["answer"].startswith("I like how openly") and why["validation_status"] == "needs_approval"

    # privacy: the AI never saw contact details
    sent = json.dumps(SENT[0])
    assert "ayesha.khan@example.com" not in sent and "+92-300" not in sent
    assert SENT[0]["job"]["company"] == "Northwind Cloud"

    # rebuild returns to the plain fact-based package
    plain = client.post(f"/api/v1/applications/{app['id']}/rebuild", headers=h).json()
    assert plain["ai"] is None and not any(b.get("ai") for e in plain["resume"]["experience"] for b in e["bullets"])


def test_paste_a_job_and_get_a_tailored_package(client, db, owner, profile, ai_on):  # noqa: F811
    h = login(client, owner)
    client.put("/api/v1/secrets", json={"name": "groq_api_key", "value": "gsk_fake_key_for_tests"}, headers=h)
    body = {
        "title": "Platform Engineer",
        "company": "Acme Health",
        "description": "We are hiring a platform engineer to run Kubernetes clusters and Terraform modules. "
        "You will build CI/CD pipelines, improve observability with Prometheus and Grafana, and support "
        "healthcare product teams. Remote within Pakistan is welcome.",
        "url": "https://careers.example.com/platform-engineer",
    }
    r = client.post("/api/v1/tailor", json=body, headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["ai_report"]["provider"] == "groq" and out["ai_error"] is None
    detail = client.get(f"/api/v1/applications/{out['application_id']}", headers=h).json()
    assert detail["job_detail"]["company"] == "Acme Health" and detail["ai"]["lines_rewritten"] >= 1
    # the same job again reuses the existing application instead of duplicating it
    again = client.post("/api/v1/tailor", json=body, headers=h).json()
    assert again["application_id"] == out["application_id"]


def test_ai_off_or_failing_keeps_the_plain_package(client, db, owner, profile, monkeypatch):  # noqa: F811
    h = login(client, owner)
    app = _prepare(client, db, owner, h)
    r = client.post(f"/api/v1/applications/{app['id']}/ai-tailor", headers=h)
    assert r.status_code == 409 and "Settings" in r.json()["detail"]

    settings_service.save(db, owner.id, UserSettings(ai=AiSettings(provider="gemini")), actor=Actor.system)
    db.commit()

    def boom(*a, **k):
        raise LLMError("Google Gemini HTTP 429: free-tier rate limit reached; wait a minute")

    monkeypatch.setattr(ai_mod, "chat_json", boom)
    r = client.post(f"/api/v1/applications/{app['id']}/ai-tailor", headers=h)
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]
    after = client.get(f"/api/v1/applications/{app['id']}", headers=h).json()
    assert after["ai"] is None and after["resume"] == app["resume"]  # untouched


def test_ai_status_and_settings(client, owner, viewer):
    h = login(client, owner)
    st = client.get("/api/v1/ai/status", headers=h).json()
    assert st["provider"] == "off" and {p["key"] for p in st["providers"]} == {"groq", "gemini", "ollama"}
    assert client.get("/api/v1/ai/status", headers=login(client, viewer)).status_code == 403
    s = client.get("/api/v1/settings", headers=h).json()
    s.pop("version")
    s["ai"]["ollama_url"] = "http://evil.example.com:11434"  # only this computer is allowed
    assert client.put("/api/v1/settings", json=s, headers=h).status_code == 422


def test_client_guards():
    with pytest.raises(LLMError, match="not an allowed"):
        endpoint(PROVIDERS["ollama"], "http://10.0.0.5:11434")
    assert endpoint(PROVIDERS["groq"]).startswith("https://api.groq.com/")
    assert parse_json('Sure!\n```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(LLMError):
        parse_json("no json here")


def test_retired_model_falls_back_and_prompt_mentions_json(monkeypatch):
    import integrations.llm as llm

    seen = []

    def fake_request(url, provider, api_key, body):
        if body is None:  # GET /models
            return json.dumps({"data": [{"id": "whisper-large-v3"}, {"id": "qwen/qwen3.8-27b"},
                                        {"id": "openai/gpt-oss-120b"}]}).encode()  # fmt: skip
        seen.append(body)
        if body["model"] == "retired-model":
            raise llm.ProviderHTTPError("Groq HTTP 404: model not found", 404, "model_not_found")
        assert "json" in body["messages"][0]["content"].lower()
        return json.dumps(
            {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"total_tokens": 5}}
        ).encode()

    monkeypatch.setattr(llm, "_request", fake_request)
    out, usage = llm.chat_json(PROVIDERS["groq"], model="retired-model", api_key="k" * 20, system="ping", user="x")
    assert out == {"ok": True} and usage["model"] == "openai/gpt-oss-120b"  # best preferred model, not whisper
    assert [b["model"] for b in seen] == ["retired-model", "openai/gpt-oss-120b"]
    assert llm.list_models(PROVIDERS["groq"], "k" * 20) == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]

    def always_401(url, provider, api_key, body):
        raise llm.ProviderHTTPError("Groq HTTP 401: the API key was rejected", 401, "invalid_api_key")

    monkeypatch.setattr(llm, "_request", always_401)
    with pytest.raises(LLMError, match="rejected"):  # other errors are not retried with another model
        llm.chat_json(PROVIDERS["groq"], model=None, api_key="k" * 20, system="ping", user="x")


def test_json_check_failure_is_retried_without_the_constraint(monkeypatch):
    import integrations.llm as llm

    modes = []

    def fake_request(url, provider, api_key, body):
        rf = body.get("response_format")
        modes.append(rf["type"] if rf else "plain")
        assert body["max_tokens"] == 50
        if rf:
            raise llm.ProviderHTTPError("Groq HTTP 400: Failed to validate JSON.", 400, "json_validate_failed")
        return json.dumps({"choices": [{"message": {"content": 'Here you go: {"ok": true}'}}]}).encode()

    monkeypatch.setattr(llm, "_request", fake_request)
    out, _ = llm.chat_json(PROVIDERS["groq"], model=None, api_key="k" * 20, system="s", user="u",
                           schema={"type": "object"}, max_tokens=50)  # fmt: skip
    assert out == {"ok": True} and modes == ["json_schema", "plain"]


def test_request_to_the_ai_is_compact_and_private(client, db, owner, profile, ai_on):  # noqa: F811
    h = login(client, owner)
    client.put("/api/v1/secrets", json={"name": "groq_api_key", "value": "gsk_fake_key_for_tests"}, headers=h)
    app = _prepare(client, db, owner, h)
    client.post(f"/api/v1/applications/{app['id']}/ai-tailor", headers=h)
    req = SENT[-1]
    kinds = {f["type"] for f in req["facts"]["items"]}
    assert {"experience", "project", "education"} <= kinds  # nothing important is cut off
    assert all("responsibilities" not in f for f in req["facts"]["items"])  # duties are sent once, as units
    assert "Kubernetes" in req["facts"]["skills_with_evidence"]
    assert len(json.dumps(req)) < 16000
