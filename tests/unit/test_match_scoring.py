from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from agents.match_agent import scoring as S
from agents.match_agent.profile import (
    CandidateProfile,
    Qualification,
    SkillEvidence,
    level_for_years,
    merged_months,
)
from agents.taxonomy import get_taxonomy
from app.schemas.settings import SENIORITY_LEVELS, UserSettings

TAX = get_taxonomy()
RECENT = datetime.now(UTC) - timedelta(days=10)
REPO = SimpleNamespace(name="k8s-lab", url="https://github.com/ayesha/k8s-lab", pushed_at=RECENT,
                       structure={"has_tests": True, "has_ci": True})  # fmt: skip


def ev(key, level="working", resume=None, high=(), medium=()):
    return SkillEvidence(key, TAX.skills[key].name, level, resume, set(high), set(medium), ["f-" + key], [])


def make_profile(skills=(), years=2.0, training=False, quals=(), certs=(), domains=None) -> CandidateProfile:
    return CandidateProfile(
        user_id=None,
        skills={s.key: s for s in skills},
        tech_years=years,
        tech_years_source=f"{int(years * 12)} months",
        tech_years_fact_ids=["f-exp"],
        training_only=training,
        level_index=level_for_years(years),
        qualifications=list(quals),
        certifications=list(certs),
        domains=domains or {},
        repos={"r1": REPO},
        pending_fact_ids=set(),
    )


def job(**kw) -> S.JobView:
    base = dict(
        title="DevOps Engineer",
        company="Acme",
        location="Remote",
        remote_type="remote",
        pk_eligibility="eligible",
        pk_evidence="location restriction includes 'Worldwide'",
        role_family="devops",
        seniority="junior",
        experience_years=2.0,
        education=None,
        visa=None,
        description="We run Kubernetes. " * 100,
        skills=[
            S.JobSkillView("kubernetes", "Kubernetes", "required", 1.0),
            S.JobSkillView("docker", "Docker", "required", 1.0),
        ],
        posted_date=date.today(),
    )
    return S.JobView(**{**base, **kw})


STRONG = [
    ev("kubernetes", "strong", "applied", high={"r1"}),
    ev("docker", "strong", "applied", high={"r1"}),
]


@pytest.mark.parametrize(
    "skill, credit, basis",
    [
        (ev("kubernetes", "strong", "applied", high={"r1"}), 1.0, "resume experience/projects and 1 GitHub repo"),
        (ev("kubernetes", "working", "applied"), 0.8, "no GitHub evidence"),
        (ev("kubernetes", "working", None, high={"r1"}), 0.7, "not shown in resume"),
        (ev("kubernetes", "exposure", "listed"), 0.5, "listed on resume only"),
        (ev("kubernetes", "exposure", None, medium={"r1"}), 0.5, "medium-strength GitHub"),
    ],
)
def test_skill_credit_tiers(skill, credit, basis):
    got, text = S.skill_credit("kubernetes", make_profile([skill]), TAX)
    assert got == credit and basis in text


def test_adjacent_skill_is_partial_and_missing_says_evidence_not_found():
    p = make_profile([ev("github_actions", "working", "applied")])
    assert S.skill_credit("gitlab_ci", p, TAX) == (0.5, "adjacent skill: GitHub Actions")
    assert S.skill_credit("ansible", p, TAX) == (0.0, "Evidence not found.")


FIVE = ("docker", "kubernetes", "helm", "terraform", "aws")


def test_perfect_fit_scores_100_and_label_never_claims_probability():
    p = make_profile([ev(k, "strong", "applied", high={"r1"}) for k in FIVE], years=2.0,
                     domains={"healthcare": "experience: Hospital Pharmacist"})  # fmt: skip
    skills = [S.JobSkillView(k, k, "required", 1.0) for k in FIVE]
    out = S.score_job(job(title="DevOps Engineer, Healthcare Platform", skills=skills), p, UserSettings(), TAX)
    assert out.score == 100 and out.qualifies and not out.knockouts
    assert out.label() == "Estimated Resume-to-Job Fit Score: 100/100 (Confidence: High)"
    assert "probability" not in out.label().lower()
    assert "not a probability of being hired" in S.DISCLAIMER
    assert sum(c["max"] for c in out.components.values()) == 100


def test_score_is_deterministic_and_uses_configured_weights():
    p = make_profile([ev("kubernetes", "working", "applied")], years=1.0)
    j = job()
    a, b = S.score_job(j, p, UserSettings(), TAX), S.score_job(j, p, UserSettings(), TAX)
    assert a.score == b.score and a.components == b.components
    heavy = UserSettings.model_validate(
        {
            "scoring_weights": {
                "skills": 60,
                "experience": 10,
                "github_evidence": 5,
                "education_certs": 5,
                "role_seniority": 10,
                "location_remote": 5,
                "domain": 5,
            }
        }  # fmt: skip
    )
    c = S.score_job(j, p, heavy, TAX)
    assert c.components["skills"]["max"] == 60 and c.score != a.score


def test_missing_and_partial_skills_are_listed():
    p = make_profile([ev("kubernetes", "exposure", "listed")])
    out = S.score_job(job(), p, UserSettings(), TAX)
    assert [m["skill"] for m in out.missing_skills] == ["docker"]
    assert out.partial_skills[0]["skill"] == "kubernetes"
    assert any("Missing required skills: Docker" in w for w in out.why_not_matched)
    assert out.evidence["docker"]["basis"] == "Evidence not found."


@pytest.mark.parametrize(
    "kw, code",
    [
        ({"pk_eligibility": "ineligible", "pk_evidence": "location restriction: 'USA'"}, "pk_ineligible"),
        ({"seniority": "senior"}, "seniority"),  # 2 years = junior; senior is 2 levels up
        ({"seniority": "manager"}, "seniority"),
        ({"experience_years": 5.0}, "experience"),  # more than 2x the verified 2 years
        ({"description": "An active security clearance is required for this role."}, "clearance"),
        ({"remote_type": "onsite", "location": "Lahore"}, "location"),
    ],
)
def test_knockouts_hide_the_job_with_a_reason(kw, code):
    out = S.score_job(job(**kw), make_profile(STRONG), UserSettings(), TAX)
    assert code in [k["code"] for k in out.knockouts]
    assert not out.qualifies and out.recommendation.startswith("Hidden: ")
    assert out.why_not_matched[0] == out.knockouts[0]["reason"]


def test_non_knockouts():
    p = make_profile(STRONG)
    ok = [
        job(description="No security clearance required. " * 60),
        job(seniority="mid"),  # one level above: scored lower, not hidden
        job(experience_years=4.0),  # exactly 2x
        job(remote_type="onsite", location="Islamabad, Pakistan"),
    ]
    for j in ok:
        assert S.score_job(j, p, UserSettings(), TAX).knockouts == [], j


def test_policy_controls_knockouts():
    s = UserSettings.model_validate(
        {"policy": {"knockout_experience_multiple": 3.0, "knockout_pk_eligibility_unknown": True}}
    )
    p = make_profile(STRONG)
    assert S.score_job(job(experience_years=5.0), p, s, TAX).knockouts == []
    assert [k["code"] for k in S.score_job(job(pk_eligibility="unknown"), p, s, TAX).knockouts] == ["pk_unknown"]


@pytest.mark.parametrize(
    "kw, ratio",
    [
        ({}, 1.0),
        ({"pk_eligibility": "unknown", "pk_evidence": "Evidence not found."}, 0.5),
        ({"remote_type": "onsite", "location": "Rawalpindi"}, 1.0),
        ({"remote_type": "hybrid", "location": "Pakistan", "pk_eligibility": "unknown"}, 0.5),
    ],
)
def test_location_component(kw, ratio):
    assert S.score_location(job(**kw), UserSettings()).ratio == ratio


@pytest.mark.parametrize(
    "req, have, ratio",
    [(None, 1.0, 0.7), (2.0, 2.0, 1.0), (2.0, 1.5, 0.8), (2.0, 1.0, 0.5), (4.0, 1.0, 0.2)],
)
def test_experience_component(req, have, ratio):
    assert S.score_experience(job(experience_years=req), make_profile(years=have)).ratio == ratio


def test_education_is_honest_about_diplomas_and_unrelated_degrees():
    quals = [
        Qualification("q1", "Doctor of Pharmacy (Pharm-D)", 4, False, False),
        Qualification("q2", "Level 6 Diploma, Artificial Intelligence Operations", 1, True, True),
    ]
    p = make_profile(quals=quals, certs=[{"fact_id": "c1", "name": "Certificate in DevOps and Cloud", "issuer": "X"}])
    strict = S.score_education(job(education="Bachelor's degree in Computer Science required"), p)
    assert strict.ratio == pytest.approx(0.5 * 0.6 + 0.4)
    assert "meets the level but not the field" in strict.explanation
    assert "is a diploma, not a degree" in strict.explanation
    lenient = S.score_education(job(education="BS in Computer Science or equivalent practical experience"), p)
    assert lenient.ratio == pytest.approx(0.7 * 0.6 + 0.4)
    certs = S.score_education(job(description="CKA certification is a plus. " * 5), p)
    assert certs.detail["requested_certs"] == ["CKA"] and certs.detail["matched_certs"] == []
    assert certs.ratio == pytest.approx(0.6)


def test_role_and_seniority_component():
    p = make_profile(years=2.0)  # junior
    assert S.score_role(job(), p, UserSettings()).ratio == 1.0
    adjacent = S.score_role(job(role_family="kubernetes", seniority=None), p, UserSettings())
    assert adjacent.ratio == pytest.approx(0.6 * 0.6 + 0.7 * 0.4)


def test_github_component_rewards_recent_tested_repos():
    p = make_profile(STRONG)
    assert S.score_github(job(), p).ratio == 1.0
    stale = SimpleNamespace(name="old", url="u", pushed_at=RECENT - timedelta(days=400), structure={})
    p.repos = {"r1": stale}
    assert S.score_github(job(), p).ratio == pytest.approx(0.8)


def test_confidence_levels():
    assert S.confidence(job(skills=[S.JobSkillView(k, k, "required", 1.0) for k in FIVE]))[0] == "high"
    thin = job(description="Short.", experience_years=None, pk_eligibility="unknown", seniority=None, skills=[])
    assert S.confidence(thin) == ("low", 0)


def test_risks_flag_training_only_experience_and_unknown_eligibility():
    p = make_profile(STRONG, years=1.1, training=True)
    p.pending_fact_ids = {"f-kubernetes"}
    out = S.score_job(job(pk_eligibility="unknown", experience_years=None), p, UserSettings(), TAX)
    text = " ".join(out.risks)
    assert "training programme" in text and "Evidence not found." in text
    assert "1 of the 3 profile facts behind this score are still pending" in text


def test_domain_needs_a_clear_signal():
    p = make_profile(domains={"healthcare": "experience: Pharmacist"})
    assert S.score_domain(job(description="We build hospital software for clinical teams."), p).ratio == 1.0
    assert S.score_domain(job(description="Our office is near a hospital."), p).ratio == 0.5  # one passing mention


def test_profile_helpers():
    assert merged_months([(date(2024, 1, 1), date(2024, 6, 1)), (date(2024, 4, 1), date(2024, 12, 1))]) == 12
    assert SENIORITY_LEVELS[level_for_years(0.5)] == "entry"
    assert SENIORITY_LEVELS[level_for_years(1.08)] == "junior"
    assert SENIORITY_LEVELS[level_for_years(6)] == "senior"
