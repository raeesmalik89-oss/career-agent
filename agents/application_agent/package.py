"""Application package: tailored resume, cover letter and standard answers, built only from profile facts.

Tailoring selects and reorders; it never writes a new claim. Every line carries the fact IDs it comes from, and
any number that is computed rather than copied (e.g. years from dated experience) is listed in `derived` so the
validator can tell it apart from an invented one. Anything that needs the user's own words is left as a
[placeholder] and routed to approval.
"""

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.match_agent.profile import CandidateProfile, _month, merged_months
from agents.match_agent.scoring import JobView, job_domains
from agents.taxonomy import Taxonomy
from app.db.models import ProfileFact, ResumeProfile
from app.schemas.settings import UserSettings

PLACEHOLDER_RX = re.compile(r"\[[^\]]{3,}\]")
MAX_TECH_BULLETS = 6
MAX_PROJECTS = 4
MAX_PROJECT_BULLETS = 3


@dataclass
class Item:
    """One generated unit (a bullet, a sentence, an answer) and the evidence it rests on."""

    text: str
    fact_ids: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)  # numbers computed from facts, not copied
    user_written: bool = False

    def dump(self) -> dict:
        return {
            "text": self.text,
            "fact_ids": self.fact_ids,
            "derived": self.derived,
            "user_written": self.user_written,
        }


@dataclass
class Answer:
    question: str
    category: str  # factual | open_ended | legal | compensation | relocation | visa | demographic
    item: Item


def _facts(db: Session, user_id: uuid.UUID) -> list[ProfileFact]:
    return [
        f
        for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id))
        if f.review_status.value != "rejected"
    ]


def _personal(facts: list[ProfileFact]) -> dict[str, tuple[object, str]]:
    return {
        f.data.get("field"): (f.data.get("value"), str(f.id))
        for f in facts
        if f.fact_type.value in ("personal", "preference") and f.data.get("field")
    }


def _relevance(text: str, techs: list[str], weights: dict[str, float], taxonomy: Taxonomy) -> float:
    keys = {h.key for h in taxonomy.find(text)} | set(techs)
    for k in list(keys):
        if k in taxonomy.skills:
            keys |= taxonomy.implied(k)
    return sum(weights.get(k, 0.0) for k in keys)


def _dates(d: dict) -> str:
    start, end = d.get("start") or "", d.get("end") or ""
    return f"{start} – {end}".strip(" –") if (start or end) else ""


def build_resume(db: Session, user_id: uuid.UUID, job: JobView, profile: CandidateProfile, taxonomy: Taxonomy) -> dict:
    facts = _facts(db, user_id)
    personal = _personal(facts)
    weights = {s.key: (1.0 if s.requirement == "required" else 0.5) for s in job.skills if s.key}

    header = {
        k: {"text": str(v), "fact_ids": [fid]}
        for k in ("name", "location", "email", "phone", "linkedin", "github")
        if k in personal
        for v, fid in [personal[k]]
    }
    rp = db.scalars(
        select(ResumeProfile).where(ResumeProfile.user_id == user_id, ResumeProfile.is_active.is_(True))
    ).first()
    # The summary is the user's own wording from their primary CV, used verbatim.
    summary = {"text": rp.summary, "fact_ids": [], "source": "primary resume summary"} if rp and rp.summary else None

    held = {k: s for k, s in profile.skills.items() if s.level is not None}
    matching = sorted(
        (k for k in weights if k in held),
        key=lambda k: (-weights[k], {"strong": 0, "working": 1, "exposure": 2}[held[k].level], held[k].name),
    )
    others = sorted(
        (k for k, s in held.items() if s.level == "strong" and k not in matching), key=lambda k: held[k].name
    )[:14]
    skills = [
        {"group": group, "items": [{"text": held[k].name, "skill": k, "fact_ids": held[k].fact_ids} for k in keys]}
        for group, keys in (("Relevant to this role", matching), ("Other strong skills", others))
        if keys
    ]

    experience = []
    exp_facts = [f for f in facts if f.fact_type.value == "experience"]
    tech = sorted(
        (f for f in exp_facts if f.data.get("sector", "tech") == "tech"),
        key=lambda f: f.data.get("end") or "",
        reverse=True,
    )
    other = [f for f in exp_facts if f.data.get("sector", "tech") != "tech"]
    # Drop umbrella entries ("Earlier career: 2020-2024") that only span other entries of the same sector.
    spans = {str(f.id): (_month(f.data.get("start"), False), _month(f.data.get("end"), True)) for f in other}

    def covers(f: ProfileFact) -> int:
        s, e = spans[str(f.id)]
        return sum(
            1
            for g in other
            if g is not f and s and e and spans[str(g.id)][0] and spans[str(g.id)][1]
            and s <= spans[str(g.id)][0] and spans[str(g.id)][1] <= e
        )  # fmt: skip

    other = sorted((f for f in other if covers(f) < 2), key=lambda f: f.data.get("end") or "", reverse=True)
    for f in tech + other:
        d = f.data
        pool = [*d.get("responsibilities", []), *d.get("details", [])] if f in tech else []
        ranked = sorted(pool, key=lambda t: -_relevance(t, [], weights, taxonomy))[:MAX_TECH_BULLETS]
        experience.append(
            {
                "title": d.get("title") or "",
                "organization": d.get("organization") or "",
                "dates": _dates(d),
                "note": "Training programme" if d.get("is_training") else None,
                "fact_ids": [str(f.id)],
                "bullets": [Item(t, [str(f.id)]).dump() for t in ranked],
                "conflicts": bool(d.get("conflicts")),
            }
        )

    projects = []
    proj_facts = [f for f in facts if f.fact_type.value == "project"]
    scored = sorted(
        proj_facts,
        key=lambda f: (
            -_relevance(" ".join(f.data.get("highlights", [])), f.data.get("technologies", []), weights, taxonomy)
        ),
    )
    for f in scored[:MAX_PROJECTS]:
        d = f.data
        bullets = sorted(d.get("highlights", []), key=lambda t: -_relevance(t, [], weights, taxonomy))
        techs = [t for t in d.get("technologies", []) if t in held]  # never list a technology without evidence
        techs = sorted(techs, key=lambda t: -weights.get(t, 0))
        repo = (d.get("github") or {}).get("repo")
        projects.append(
            {
                "name": d.get("name") or "",
                "technologies": [taxonomy.skills[t].name if t in taxonomy.skills else t for t in techs[:8]],
                "repo": f"github.com/{personal['github'][0].split('/')[-1]}/{repo}"
                if repo and "github" in personal
                else None,
                "fact_ids": [str(f.id)],
                "bullets": [Item(t, [str(f.id)]).dump() for t in bullets[:MAX_PROJECT_BULLETS]],
            }
        )

    education = [
        {
            "qualification": f.data.get("qualification") or "",
            "institution": f.data.get("institution") or "",
            "date": f.data.get("date") or "",
            "grade": f.data.get("grade"),
            "fact_ids": [str(f.id)],
        }
        for f in sorted(
            (f for f in facts if f.fact_type.value == "education"), key=lambda f: f.data.get("date") or "", reverse=True
        )
    ]
    certifications = [
        {
            "name": f.data.get("name") or "",
            "issuer": f.data.get("issuer"),
            "issued": f.data.get("issued") or f.data.get("validity"),
            "credential_id": f.data.get("credential_id"),
            "fact_ids": [str(f.id)],
        }
        for f in facts
        if f.fact_type.value == "certification"
    ]
    languages = personal.get("languages")
    return {
        "header": header,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": education,
        "certifications": certifications,
        "languages": {"items": languages[0], "fact_ids": [languages[1]]} if languages else None,
    }


def _sector_years(facts: list[ProfileFact], sector: str) -> tuple[float, list[str]]:
    periods, ids = [], []
    for f in facts:
        if f.fact_type.value == "experience" and f.data.get("sector") == sector:
            s, e = _month(f.data.get("start"), False), _month(f.data.get("end"), True)
            if s and e and s <= e:
                periods.append((s, e))
                ids.append(str(f.id))
    return round(merged_months(periods) / 12, 1), ids


def build_cover_letter(
    db: Session, user_id: uuid.UUID, job: JobView, profile: CandidateProfile, resume: dict
) -> list[Item]:
    facts = _facts(db, user_id)
    personal = _personal(facts)
    paras: list[Item] = []
    where = f" in {job.location}" if job.location and job.remote_type != "remote" else ""
    paras.append(Item(f"Dear {job.company} hiring team,"))
    paras.append(Item(f"I am applying for the {job.title} role{where}."))

    tech_exp = next((e for e in resume["experience"] if e["note"] == "Training programme"), None) or next(
        iter(resume["experience"]), None
    )
    diploma = next((e for e in resume["education"] if "diploma" in e["qualification"].lower()), None)
    if tech_exp:
        text = f"I recently completed the {tech_exp['title']} at {tech_exp['organization'].split(',')[0]}"
        text += f" ({tech_exp['dates']})" if tech_exp["dates"] else ""
        ids = list(tech_exp["fact_ids"])
        if diploma:
            text += f", part of my {diploma['qualification']}"
            ids += diploma["fact_ids"]
        paras.append(Item(text + ".", ids))

    matched = [s for s in job.skills if s.key and s.key in profile.skills and profile.skills[s.key].gh_high]
    if matched:
        names = []
        ids: list[str] = []
        for s in sorted(matched, key=lambda s: s.requirement != "required")[:4]:
            names.append(profile.skills[s.key].name)
            ids += profile.skills[s.key].fact_ids
        gh = personal.get("github")
        text = f"My public GitHub repositories{f' ({gh[0]})' if gh else ''} contain working code and configuration for "
        text += ", ".join(names[:-1]) + (f" and {names[-1]}" if len(names) > 1 else names[0]) + "."
        paras.append(Item(text, ids + ([gh[1]] if gh else [])))

    for p in resume["projects"][:2]:
        if p["bullets"]:
            paras.append(Item(f"{p['name']}: {p['bullets'][0]['text']}", p["fact_ids"]))

    if "healthcare" in job_domains(job):
        years, ids = _sector_years(facts, "healthcare")
        if years:
            paras.append(
                Item(
                    f"Before moving into technology I spent {years:g} years in healthcare as a pharmacist, which "
                    "helps me understand the clinical context of your work.",
                    ids,
                    derived=[f"{years:g}"],
                )
            )
    paras.append(Item(f"[Why {job.company}: write one or two sentences in your own words.]"))
    closing = "Thank you for considering my application."
    contact = [personal[k] for k in ("name", "email", "phone") if k in personal]
    paras.append(Item(closing))
    if contact:
        paras.append(Item("\n".join(str(v) for v, _ in contact), [fid for _, fid in contact]))
    return paras


def build_answers(
    db: Session, user_id: uuid.UUID, job: JobView, profile: CandidateProfile, settings: UserSettings, resume: dict
) -> list[Answer]:
    facts = _facts(db, user_id)
    personal = _personal(facts)
    out: list[Answer] = []
    for field_, question in (
        ("name", "Full name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("location", "Current location"),
        ("linkedin", "LinkedIn profile"),
        ("github", "GitHub profile"),
    ):
        if field_ in personal:
            v, fid = personal[field_]
            out.append(Answer(question, "factual", Item(str(v), [fid])))

    months = round(profile.tech_years * 12)
    exp_text = f"{profile.tech_years:g} years"
    if profile.training_only:
        tr = next((e for e in resume["experience"] if e["note"] == "Training programme"), None)
        exp_text += f" ({months}-month hands-on training programme" + (f": {tr['title']}" if tr else "") + ")"
    out.append(
        Answer(
            "Years of relevant experience",
            "factual",
            Item(exp_text, list(profile.tech_years_fact_ids), derived=[f"{profile.tech_years:g}", str(months)]),
        )
    )
    if resume["education"]:
        top = max(profile.qualifications, key=lambda q: q.level, default=None)
        edu = next((e for e in resume["education"] if top and e["fact_ids"] == [top.fact_id]), resume["education"][0])
        out.append(
            Answer(
                "Highest qualification",
                "factual",
                Item(
                    f"{edu['qualification']}, {edu['institution']} ({edu['date']})".replace(" ()", ""), edu["fact_ids"]
                ),
            )
        )
    if "availability" in personal:
        v, fid = personal["availability"]
        out.append(Answer("Availability / notice period", "factual", Item(str(v), [fid])))

    prefs = settings.preferences
    out.append(
        Answer(
            "Do you require visa sponsorship?",
            "visa",
            Item("Yes" if prefs.needs_visa_sponsorship else "No", derived=[], user_written=True),
        )
    )
    out.append(
        Answer(
            "Are you willing to relocate?",
            "relocation",
            Item("Yes" if prefs.willing_to_relocate else "No", user_written=True),
        )
    )
    pkr = prefs.salary.min_monthly_pkr
    usd = prefs.salary.min_annual_usd
    salary = (
        f"PKR {pkr:,} per month" if pkr and job.remote_type != "remote" else f"USD {usd:,} per year" if usd else None
    )
    out.append(
        Answer(
            "Expected salary",
            "compensation",
            Item(salary, user_written=True, derived=[str(pkr or usd)])
            if salary
            else Item("[Your expected salary: not set in Settings]"),
        )
    )
    out.append(Answer(f"Why do you want to work at {job.company}?", "open_ended", Item(f"[Why {job.company}]")))
    return out
