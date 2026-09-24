"""Questions about the user's own CV and GitHub: project defence, metric defence and personal HR questions.

Model answers here are outlines assembled only from the user's facts (they must be told in the user's own
words); nothing is invented. Only technologies the user has evidence for are asked about.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.interview_agent.bank import KeyPoint
from agents.match_agent.profile import CandidateProfile
from agents.taxonomy import Taxonomy
from app.db.models import ProfileFact

METRIC_RX = re.compile(
    r"[<>~]?\d+(?:[.,]\d+)?\s?(?:%|ms\b|s\b|x\b|min\b|minutes|seconds|hours|patients|records|(?:micro)?services|"
    r"nodes|pods|clusters|users|requests|partitions|features)",
    re.I,
)


@dataclass
class PersonalQuestion:
    bank_id: str
    section: str  # project | hr
    q: str
    tests: str
    points: list[KeyPoint]
    ideal: str
    mistakes: list[str]
    follow_up: str
    spoken: str
    skills: list[str]
    fact_ids: list[str]
    difficulty: str = "medium"


def _kp(label: str, *terms: str) -> KeyPoint:
    return KeyPoint(label, tuple(t for t in terms if t) or (label,))


def _tech_point(key: str, taxonomy: Taxonomy) -> KeyPoint:
    s = taxonomy.skills.get(key)
    return _kp(f"mention {s.name if s else key}", *((s.name, *s.aliases) if s else (key,)))


def _short(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _live_facts(db: Session, user_id: uuid.UUID) -> list[ProfileFact]:
    return [
        f
        for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id))
        if f.review_status.value != "rejected"
    ]


def _walkthrough(f: ProfileFact, techs: list[str], taxonomy: Taxonomy) -> PersonalQuestion:
    d = f.data
    name = d.get("name") or "your project"
    repo = (d.get("github") or {}).get("repo")
    outline = "; ".join(_short(h, 140) for h in d.get("highlights", [])[:4])
    repo_note = (
        f" The code is public in the {repo} repository, so be ready to open it and explain any file."
        if repo
        else " No public repository is linked to it, so expect questions that test you really built it."
    )
    return PersonalQuestion(
        bank_id=f"project:{f.id}:walkthrough",
        section="project",
        q=f"Walk me through your project “{name}”. What problem did it solve, how is it built, and what was your part?",
        tests="Whether you really built it: architecture, reasons, your role and results.",
        points=[
            _kp("the problem or goal", "problem", "goal", "needed", "purpose", "use case"),
            *[_tech_point(t, taxonomy) for t in techs],
            _kp("why these choices", "because", "chose", "instead", "trade-off", "why"),
            _kp("a result or what you learned", "result", "reduced", "improved", "learned", "%"),
        ],
        ideal=(
            "Answer in four parts, in your own words: 1) the problem it solves, 2) the architecture from input to "
            "output, 3) what you personally built and why you chose each tool, 4) the result and what you would "
            f"improve. From your CV: {outline or 'add highlights to this project in your profile'}.{repo_note}"
        ),
        mistakes=[
            "Listing tools without saying why each was chosen.",
            "Claiming results you cannot explain or reproduce.",
        ],
        follow_up="What was the hardest problem you hit, and how did you debug it?",
        spoken=f"I built {name} to solve a specific problem. I will explain the architecture, what I did myself, "
        "why I chose the tools, and the result.",
        skills=techs,
        fact_ids=[str(f.id)],
    )


def _metric(f: ProfileFact, highlight: str, metric: str, techs: list[str]) -> PersonalQuestion:
    digest = hashlib.sha256(highlight.encode()).hexdigest()[:10]
    return PersonalQuestion(
        bank_id=f"metric:{f.id}:{digest}",
        section="project",
        q=f"Your CV says: “{_short(highlight, 160)}”. How exactly did you measure {metric}?",
        tests="Whether the numbers on your CV are real and you understand them.",
        points=[
            # essential: the answer must actually be about this number, not about another result
            _kp(f"talk about the {metric} itself", re.sub(r"[^\d.,]", "", metric) or metric),
            _kp(
                "how it was measured",
                "measured",
                "prometheus",
                "grafana",
                "logs",
                "benchmark",
                "test",
                "script",
                "metric",
                "timer",
                "load test",
                "evaluation",
            ),  # fmt: skip
            _kp("the baseline or comparison", "before", "baseline", "compared", "previously", "from"),
            _kp("the conditions", "data", "load", "environment", "dataset", "lab", "local", "cluster"),
            _kp("honest limits", "limitation", "lab", "simulated", "small", "not production", "only", "would need"),
        ],
        ideal=(
            f"Explain the measurement behind {metric}: the tool or method (for example Prometheus metrics, logs, a "
            "benchmark script or a held-out test set), the baseline you compared against, and the conditions (lab "
            "environment, dataset size, load). Be honest about limits, such as a lab or dataset result rather than "
            "production traffic. If you cannot explain a number clearly, remove it from your CV before the interview."
        ),
        mistakes=["Giving a vague answer, which makes the interviewer doubt the whole CV."],
        follow_up="Would that number hold in production? What would change?",
        spoken=f"I measured {metric} with a clear method, compared it with a baseline, in a lab setting, "
        "and I know its limits.",
        skills=techs,
        fact_ids=[str(f.id)],
        difficulty="hard",
    )


def project_questions(
    db: Session, user_id: uuid.UUID, profile: CandidateProfile, taxonomy: Taxonomy, relevance: dict[str, float]
) -> list[PersonalQuestion]:
    projects = [f for f in _live_facts(db, user_id) if f.fact_type.value == "project"]
    projects.sort(key=lambda f: sum(relevance.get(t, 0) for t in f.data.get("technologies", [])), reverse=True)
    out: list[PersonalQuestion] = []
    for f in projects:
        held = [t for t in f.data.get("technologies", []) if t in profile.skills and profile.skills[t].level]
        techs = sorted(held, key=lambda t: -relevance.get(t, 0))[:4]
        out.append(_walkthrough(f, techs, taxonomy))
        for h in f.data.get("highlights", []):
            metrics = METRIC_RX.findall(h)
            if metrics:
                out.append(_metric(f, h, metrics[0].strip(), techs))
    return out


def personal_hr_questions(db: Session, user_id: uuid.UUID, profile: CandidateProfile) -> list[PersonalQuestion]:
    facts = _live_facts(db, user_id)
    exp = [f for f in facts if f.fact_type.value == "experience"]
    tech = [f for f in exp if f.data.get("sector", "tech") == "tech"]
    other = [f for f in exp if f.data.get("sector") not in (None, "tech")]
    edu = [f for f in facts if f.fact_type.value == "education"]
    projects = [f for f in facts if f.fact_type.value == "project"]
    out: list[PersonalQuestion] = []

    parts = []
    if edu:
        parts.append(f"education: {edu[0].data.get('qualification')}")
    if tech:
        t = tech[0].data
        parts.append(f"technology experience: {t.get('title')} ({t.get('start')} – {t.get('end')})")
    if projects:
        parts.append("projects: " + ", ".join(p.data.get("name", "") for p in projects[:2]))
    if other:
        sectors = sorted({f.data.get("sector") for f in other})
        parts.append(f"earlier career: {', '.join(sectors)} ({len(other)} roles)")
    out.append(
        PersonalQuestion(
            bank_id="personal:about",
            section="hr",
            q="Tell me about yourself.",
            tests="A clear, relevant 60-90 second story that leads to this role.",
            points=[
                _kp("where you are now", "currently", "recently", "now", "completed", "diploma", "training"),
                _kp(
                    "relevant skills or a project",
                    "project",
                    "built",
                    "kubernetes",
                    "docker",
                    "aws",
                    "azure",
                    "terraform",
                    "pipeline",
                ),  # fmt: skip
                _kp("your background and how it helps", "background", "before", "previously", "healthcare", "pharmac"),
                _kp("why this role now", "looking for", "this role", "want to", "goal", "next"),
            ],
            ideal=(
                "Present, past, future in about a minute: where you are now, the most relevant thing you have built, "
                "how your background helps, and why this role is your next step. Your facts: "
                + ("; ".join(parts) or "import your CV to fill this in")
                + ". Say it in your own words; do not recite your CV."
            ),
            mistakes=["Reading your CV line by line.", "Talking for more than two minutes."],
            follow_up="What are you proudest of in your projects?",
            spoken="Right now I am focused on DevOps and cloud. I recently built projects like the ones on my CV. "
            "Before that I worked in another field, which taught me useful habits. Now I want to grow in this role.",
            skills=[],
            fact_ids=[str(f.id) for f in (edu[:1] + tech[:1] + projects[:2])],
        )
    )
    if other and tech:
        sector = other[0].data.get("sector")
        out.append(
            PersonalQuestion(
                bank_id="personal:career-change",
                section="hr",
                q=f"You worked in {sector} before. Why are you moving into technology?",
                tests="A convincing, positive career-change story.",
                points=[
                    _kp("what drew you to technology", "automat", "interest", "enjoy", "systems", "data", "technology"),
                    _kp("what you did about it", "diploma", "training", "course", "project", "built", "learned"),
                    _kp(
                        "what transfers from before",
                        "responsib",
                        "safety",
                        "pressure",
                        "detail",
                        "patients",
                        "regulat",
                        "process",
                    ),  # fmt: skip
                    _kp("positive framing, not escaping", "moving towards", "want to", "goal", "combine", "both"),
                ],
                ideal=(
                    "Frame it as moving towards something: what you discovered you enjoy about technology, the "
                    "concrete steps you took (your diploma, the training programme and your projects), and what "
                    f"transfers from {sector}: attention to detail, working under pressure, following safety and "
                    "regulatory processes. If the role is in a related domain (for example health tech), say how you "
                    "combine both."
                ),
                mistakes=["Speaking negatively about your previous profession."],
                follow_up="Why should we hire you over someone who studied computer science?",
                spoken="I discovered I enjoy building and automating systems, so I trained for it and built projects. "
                "My earlier work taught me care, safety and working under pressure, which also matter in operations.",
                skills=[],
                fact_ids=[str(f.id) for f in (other[:1] + tech[:1])],
            )
        )
    if profile.training_only:
        out.append(
            PersonalQuestion(
                bank_id="personal:training-only",
                section="hr",
                q="Most of your DevOps experience is from a training programme. "
                "Why should we trust you with production?",
                tests="Honest confidence about experience level.",
                points=[
                    _kp("honest about the level", "training", "honest", "not yet", "junior", "lab"),
                    _kp("concrete evidence", "project", "github", "built", "deployed", "repository"),
                    _kp("how you work safely", "review", "ask", "rollback", "test", "careful", "runbook", "staging"),
                    _kp("learning speed", "learn", "quickly", "fast", "certif", "diploma"),
                ],
                ideal=(
                    f"Be honest: your hands-on experience is {profile.tech_years:g} years from a structured training "
                    "programme and your own projects, not production employment. Then give evidence: specific things "
                    "you built and can show on GitHub, and how you work safely as a newcomer (asking for reviews, "
                    "testing in staging, knowing how to roll back, following runbooks). End with how quickly you "
                    "learn, with an example."
                ),
                mistakes=["Overstating the training as full professional experience."],
                follow_up="What would you do in your first on-call shift if something broke that you did not "
                "understand?",
                spoken="It is true my experience is from training and my own projects. But I built real things you "
                "can see on GitHub, I work carefully with reviews and rollbacks, and I learn fast.",
                skills=[],
                fact_ids=list(profile.tech_years_fact_ids),
            )
        )
    return out
