import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from agents.interview_agent import service
from agents.interview_agent.bank import get_bank
from agents.interview_agent.pack import generate_pack
from app.db.models import InterviewQuestion
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture

GOOD = (
    "First I run kubectl describe pod to read the events and the exit code, because it shows whether it was "
    "OOMKilled. Then kubectl logs --previous for the crashed container. I check the ConfigMap, Secret and env "
    "values, and whether probes or memory limits are too strict. However, if a dependency is down I test it."
)


def test_daily_pack_has_six_sections_and_uses_the_profile(client, db, owner, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    h = login(client, owner)
    pack = client.get("/api/v1/interview/packs/today", headers=h).json()
    assert pack["total"] == 60
    keys = [s["key"] for s in pack["sections"]]
    assert keys == ["target", "gaps", "projects", "scenarios", "design", "hr"]
    counts = {s["key"]: len(s["questions"]) for s in pack["sections"]}
    # every section is present; a thin CV (one project here) leaves its slots to the other sections
    assert all(n >= 1 for n in counts.values()) and counts["hr"] >= 8 and counts["scenarios"] == 10, counts
    projects = next(s for s in pack["sections"] if s["key"] == "projects")["questions"]
    # project defence comes from the imported CV project, and CV numbers get their own question
    assert any("Kubernetes Observability Stack" in q["question"] for q in projects)
    assert any(q["question"].startswith("Your CV says") and "12" in q["question"] for q in projects)
    hr = next(s for s in pack["sections"] if s["key"] == "hr")["questions"]
    assert any(q["question"] == "Tell me about yourself." for q in hr)
    ids = [q["bank_id"] for s in pack["sections"] for q in s["questions"]]
    assert len(ids) == len(set(ids))  # no question twice in one pack
    # the same day returns the same pack
    again = client.get("/api/v1/interview/packs/today", headers=h).json()
    assert [q["id"] for s in again["sections"] for q in s["questions"]] == [
        q["id"] for s in pack["sections"] for q in s["questions"]
    ]


def test_mock_interview_hides_the_model_answer_until_answered(client, db, owner, viewer, profile):  # noqa: F811
    db.commit()
    h = login(client, owner)
    assert client.post("/api/v1/interview/sessions", json={"mode": "nope"}, headers=h).status_code == 422
    assert (
        client.post("/api/v1/interview/sessions", json={"mode": "pack"}, headers=login(client, viewer)).status_code
        == 403
    )

    s = client.post("/api/v1/interview/sessions", json={"mode": "pack", "count": 6}, headers=h)
    assert s.status_code == 201, s.text
    session = s.json()
    assert session["total"] == 6 and session["answered"] == 0
    nxt = session["next"]
    assert set(nxt) >= {"question_id", "question", "tests", "index", "total"}
    assert "model_answer" not in nxt and "ideal" not in str(nxt).lower()
    sections = Counter()
    for i in range(6):
        sections[nxt["section"]] += 1
        body = {"question_id": nxt["question_id"], "answer": GOOD if i == 0 else "Not sure."}
        r = client.post(f"/api/v1/interview/sessions/{session['id']}/answer", json=body, headers=h)
        assert r.status_code == 200, r.text
        fb = r.json()
        assert fb["model_answer"] and fb["spoken_version"] and fb["disclaimer"].startswith("Automatic feedback")
        assert set(fb["rubric"]) == {"accuracy", "completeness", "structure", "depth", "communication"}
        nxt = fb["next"]
        if i < 5:
            assert nxt is not None
    assert nxt is None and len(sections) >= 4  # the mixed session spans sections
    again = client.post(f"/api/v1/interview/sessions/{session['id']}/answer",
                        json={"question_id": fb["question_id"], "answer": "x"}, headers=h)  # fmt: skip
    assert again.status_code == 409

    done = client.get(f"/api/v1/interview/sessions/{session['id']}", headers=h).json()
    assert done["ended_at"] and done["answered"] == 6 and done["avg_score"] is not None

    stats = client.get("/api/v1/interview/stats", headers=h).json()
    assert stats["answers"] == 6 and stats["sessions"] == 1 and stats["weakest"]
    assert client.get("/api/v1/interview/stats", headers=login(client, viewer)).json()["answers"] == 0


def test_weak_answers_come_back_in_tomorrows_pack(db, owner, profile):  # noqa: F811
    today = datetime.now(UTC).date()
    s = service.start_session(db, owner.id, "scenarios", 3, today)
    weak = []
    while (nxt := service.next_question(db, s)) is not None:
        qid = uuid.UUID(nxt["question_id"])
        fb = service.answer(db, s, qid, "Restart it.")
        assert fb["score"] < 70
        weak.append(db.get(InterviewQuestion, qid).bank_id)
    tomorrow = generate_pack(db, owner.id, today + timedelta(days=1))
    assert set(weak) <= {q.bank_id for q in tomorrow}
    # questions never shown before are chosen ahead of repeats
    first = {q.bank_id for q in generate_pack(db, owner.id, today)}
    never_shown = set(get_bank()) - first
    assert never_shown <= {q.bank_id for q in tomorrow}
