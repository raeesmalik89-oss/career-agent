from collections import Counter

import pytest

from agents.interview_agent.bank import KeyPoint, get_bank, load_bank
from agents.interview_agent.rubric import WEIGHTS, evaluate

BANK = get_bank()


def test_bank_is_valid_and_covers_every_section():
    assert len(BANK) >= 70
    sections = Counter(q.section for q in BANK.values())
    assert set(sections) == {"core", "scenario", "design", "hr"}
    for q in BANK.values():
        assert len(q.points) >= 2 and q.ideal and q.spoken and q.follow_up and q.mistakes, q.id
        # every model answer must itself cover its own essential key points
        essential = q.points[: max(2, (len(q.points) + 1) // 2)]
        covered = [p.label for p in essential if p.covered_by(q.ideal)]
        assert len(covered) >= len(essential) - 1, (q.id, [p.label for p in essential if p.label not in covered])


def test_model_answers_score_well_against_their_own_rubric():
    low = []
    for q in BANK.values():
        ev = evaluate(q.ideal, list(q.points), ideal=q.ideal, behavioural=q.section == "hr")
        if ev.score < 70:
            low.append((q.id, ev.score))
    assert not low, low


def test_bad_bank_entries_are_rejected(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "- {id: a, section: core, difficulty: easy, q: Q, tests: T, points: [[one, x]], ideal: I, "
        "mistakes: [m], follow_up: F, spoken: S}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="at least 2 key points"):
        load_bank(tmp_path)
    (tmp_path / "x.yaml").write_text(
        "- {id: a, section: core, skills: [not_a_skill], difficulty: easy, q: Q, tests: T, "
        "points: [[one, x], [two, y]], ideal: I, mistakes: [m], follow_up: F, spoken: S}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown skills"):
        load_bank(tmp_path)


def test_rubric_weights_match_the_architecture():
    assert WEIGHTS == {"accuracy": 40, "completeness": 25, "structure": 15, "depth": 10, "communication": 10}


def test_empty_and_short_answers_score_low_with_reasons():
    q = BANK["k8s-crashloop"]
    empty = evaluate("", list(q.points), ideal=q.ideal, behavioural=False)
    assert empty.score <= 15 and "No answer given." in empty.mistakes
    short = evaluate("Check the logs.", list(q.points), ideal=q.ideal, behavioural=False)
    assert short.score < 40 and any("Too short" in m for m in short.mistakes)
    assert "check exit code and OOMKilled" in short.missing


def test_good_technical_answer_scores_high():
    q = BANK["k8s-crashloop"]
    answer = (
        "First I run kubectl describe pod to read the events and the exit code, because it tells me whether it was "
        "OOMKilled. Then kubectl logs --previous to see why the last container crashed. I check the ConfigMap, "
        "Secret and env values, and whether the liveness probe or memory limits are too strict. However, if it is a "
        "dependency, I test the connection from inside the cluster."
    )
    ev = evaluate(answer, list(q.points), ideal=q.ideal, behavioural=False)
    assert ev.score >= 85 and not ev.missing


def test_behavioural_answer_is_judged_on_star():
    q = BANK["hr-failure"]
    flat = evaluate("Kubernetes is hard and sometimes things fail but that is normal in DevOps work for everyone.",
                    list(q.points), ideal=q.ideal, behavioural=True)  # fmt: skip
    star = evaluate(
        "During my training lab I had to deploy an app to AKS. I deployed it but it broke because the readiness "
        "probe pointed to the wrong port; that was my mistake. I investigated with kubectl describe, fixed the port "
        "and rolled out again. As a result it worked, and I learned to add a smoke test to the pipeline so it cannot "
        "happen again.",
        list(q.points),
        ideal=q.ideal,
        behavioural=True,
    )
    assert star.score > flat.score + 30
    assert any("story" in m for m in flat.mistakes)


def test_red_flags_are_reported():
    q = BANK["linux-permissions"]
    ev = evaluate("I would just chmod 777 the folder so it works.", list(q.points), ideal=q.ideal, behavioural=False,
                  red_flags=q.red_flags)  # fmt: skip
    assert any("777" in m for m in ev.mistakes)


def test_anchored_question_caps_off_topic_answers():
    pts = [KeyPoint("talk about the 70%", ("70",)), KeyPoint("how measured", ("measured",)),
           KeyPoint("baseline", ("baseline",)), KeyPoint("conditions", ("lab",))]  # fmt: skip
    off = ("I built it because I needed scoring. Kafka streams data and FastAPI serves it. As a result latency "
           "stayed low in my lab, measured with Prometheus compared to the baseline.")  # fmt: skip
    ev = evaluate(off, pts, ideal="x " * 60, behavioural=False, anchored=True)
    assert ev.score <= 40 and ev.mistakes[0].startswith("Your answer does not address the question")
    assert evaluate(off, pts, ideal="x " * 60, behavioural=False).score > 40
