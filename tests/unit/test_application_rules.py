from types import SimpleNamespace

from agents.application_agent.policy import decide_prepare, decide_submission
from agents.application_agent.validator import validate_item
from agents.match_agent.profile import CandidateProfile, SkillEvidence
from agents.taxonomy import get_taxonomy
from app.schemas.settings import UserSettings

TAX = get_taxonomy()


def fact(fid, status="verified", **data):
    return SimpleNamespace(id=fid, review_status=SimpleNamespace(value=status), data=data)


def profile(*keys) -> CandidateProfile:
    return CandidateProfile(
        user_id=None,
        skills={k: SkillEvidence(k, TAX.skills[k].name, "working", "applied") for k in keys},
        tech_years=1.0, tech_years_source="", tech_years_fact_ids=[], training_only=False, level_index=2,
        qualifications=[], certifications=[], domains={}, repos={}, pending_fact_ids=set(),
    )  # fmt: skip


FACTS = {
    "p1": fact("p1", highlights=["Cut deploy time from 30 min to 5 min with Kubernetes and Helm."]),
    "pending": fact("pending", status="pending", text="Built Terraform modules."),
    "rej": fact("rej", status="rejected", text="Led a team of 10."),
    "conf": fact("conf", title="DevOps Intern", conflicts=[{"field": "title"}]),
}
P = profile("kubernetes", "helm", "terraform")


def check(text, ids=(), **kw):
    return validate_item({"text": text, "fact_ids": list(ids), **kw}, FACTS, P, TAX)


def test_copied_fact_is_valid():
    v = check("Cut deploy time from 30 min to 5 min with Kubernetes and Helm.", ["p1"])
    assert v.status == "valid", v.notes


def test_invented_number_is_unsupported():
    v = check("Cut deploy time from 30 min to 2 min with Kubernetes.", ["p1"])
    assert v.status == "unsupported" and any("2" in n and "Evidence not found." in n for n in v.notes)


def test_derived_number_is_allowed():
    assert check("I have 1.5 years of experience.", ["p1"], derived=["1.5"]).status == "valid"


def test_unevidenced_technology_is_unsupported_unless_user_wrote_it():
    assert check("Deployed with Kubernetes and Ansible.", ["p1"]).status == "unsupported"
    mine = check("I have used Ansible at home.", [], user_written=True)
    assert mine.status == "needs_approval" and "Ansible" in mine.notes[0]


def test_rejected_or_missing_facts_are_unsupported():
    assert check("Led a team of 10.", ["rej"]).status == "unsupported"
    assert check("Something.", ["nope"]).status == "unsupported"


def test_pending_conflicted_and_placeholder_need_approval():
    assert check("Built Terraform modules.", ["pending"]).status == "needs_approval"
    assert check("Intern at Acme", ["conf"]).status == "needs_approval"
    v = check("[Why Acme: write in your own words]")
    assert v.status == "needs_approval" and "own words" in v.notes[0]


def test_prepare_policy_records_user_override():
    s = UserSettings()
    auto = decide_prepare(score=70, knockouts=[], settings=s, requested_by_user=False)
    assert auto.outcome == "skip" and auto.trace[0] == {"rule": "score_at_or_above_threshold", "passed": False,
                                                        "detail": "70 vs threshold 80"}  # fmt: skip
    mine = decide_prepare(score=70, knockouts=[{"reason": "too senior"}], settings=s, requested_by_user=True)
    assert mine.outcome == "prepare" and mine.trace[-1]["rule"] == "requested_by_user"


def _submit(**kw):
    base = dict(settings=UserSettings(), source_auto_apply_allowed=True, answers=[],
                resume_counts={"unsupported": 0, "needs_approval": 0}, match_confidence="high",
                pk_eligibility="eligible", auto_submits_today=0)  # fmt: skip
    return decide_submission(**{**base, **kw})


def test_default_settings_never_auto_submit():
    d = _submit()
    assert d.outcome == "pending_approval"
    assert {r["rule"]: r["passed"] for r in d.trace}["auto_apply_enabled"] is False


def test_auto_submit_only_when_every_rule_passes():
    on = UserSettings.model_validate({"preferences": {"auto_apply": True}})
    assert _submit(settings=on).outcome == "auto_submit"
    for kw in (
        {"source_auto_apply_allowed": False},
        {"answers": [{"category": "open_ended", "validation_status": "valid"}]},
        {"answers": [{"category": "factual", "validation_status": "unsupported"}]},
        {"resume_counts": {"needs_approval": 1}},
        {"match_confidence": "low"},
        {"pk_eligibility": "unknown"},
        {"auto_submits_today": 5},
    ):
        assert _submit(settings=on, **kw).outcome == "pending_approval", kw
