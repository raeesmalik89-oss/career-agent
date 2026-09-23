"""Deterministic, explainable Estimated Resume-to-Job Fit Score (docs/ARCHITECTURE.md section 5).

Pure functions only: the same job + profile + settings always give the same score. No LLM computes anything here.
The score measures overlap between the verified profile and a posting. It is never a hiring probability.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from agents.job_agent.extract import clearance_quote, is_summary
from agents.match_agent.profile import TECH_FIELD_RX, CandidateProfile
from agents.taxonomy import Taxonomy
from app.schemas.settings import SENIORITY_LEVELS, UserSettings

LABEL = "Estimated Resume-to-Job Fit Score"
DISCLAIMER = "Measures overlap between your verified profile and the posting. It is not a probability of being hired."
NOT_FOUND = "Evidence not found."

ADJACENT_FAMILIES = {
    "devops": {"sre", "platform", "cloud", "devsecops", "kubernetes", "aiops"},
    "sre": {"devops", "sre_ai", "platform", "aiops"},
    "sre_ai": {"sre", "aiops", "cloud_ai_infra"},
    "aiops": {"sre", "devops", "mlops", "sre_ai"},
    "mlops": {"ai_platform", "ai_engineer", "aiops", "cloud_ai_infra"},
    "ai_platform": {"mlops", "cloud_ai_infra", "ai_engineer"},
    "ai_engineer": {"mlops", "ai_platform"},
    "cloud": {"devops", "platform", "cloud_ai_infra", "devsecops"},
    "cloud_ai_infra": {"cloud", "mlops", "ai_platform"},
    "platform": {"devops", "kubernetes", "cloud", "sre"},
    "kubernetes": {"platform", "devops"},
    "devsecops": {"devops", "cloud"},
}
# Seniority titles outside the ladder, mapped to the closest rung for gap checks.
SENIORITY_ALIASES = {"manager": "staff", "lead": "senior", "director": "principal"}

CERT_PATTERNS = {
    "CKA": r"\bCKA\b|certified kubernetes administrator",
    "CKAD": r"\bCKAD\b|certified kubernetes application developer",
    "CKS": r"\bCKS\b|certified kubernetes security",
    "AWS certification": r"\baws certified\b|aws (solutions architect|devops engineer|sysops)[^.\n]{0,20}certif",
    "Azure certification": r"\bAZ-\d{3}\b|azure (administrator|devops engineer|solutions architect)"
    r"[^.\n]{0,15}(associate|expert)",
    "GCP certification": r"google cloud (certified|professional)|\bprofessional cloud (architect|devops engineer)\b",
    "Terraform Associate": r"terraform (associate|certif)",
    "Security+": r"security\+|comptia security",
    "CISSP": r"\bCISSP\b",
    "RHCSA/RHCE": r"\bRHC(SA|E)\b|red hat certified",
}
DOMAIN_RX = {
    "healthcare": re.compile(
        r"\b(health ?care|health ?tech|clinical|hospital|pharma\w*|medical|patients?|ehr|hipaa|life sciences)\b", re.I
    ),
    "aiops": re.compile(r"\b(aiops|ai ops|ai operations|anomaly detection|self-healing|auto-remediation)\b", re.I),
    "mlops": re.compile(r"\b(mlops|ml platform|model (deployment|serving)|machine learning infrastructure)\b", re.I),
    "security": re.compile(r"\b(devsecops|cloud security|application security|security engineering)\b", re.I),
}


@dataclass
class JobSkillView:
    key: str | None
    name: str
    requirement: str  # required | preferred
    weight: float


@dataclass
class JobView:
    title: str
    company: str
    location: str | None
    remote_type: str
    pk_eligibility: str
    pk_evidence: str | None
    role_family: str | None
    seniority: str | None
    experience_years: float | None
    education: str | None
    visa: str | None
    description: str
    skills: list[JobSkillView]
    posted_date: date | None = None
    salary_known: bool = False

    @property
    def summary_only(self) -> bool:
        return is_summary(self.description)


@dataclass
class Component:
    ratio: float
    explanation: str
    detail: dict = field(default_factory=dict)


@dataclass
class MatchOutcome:
    score: float
    confidence: str
    confidence_points: int
    components: dict[str, dict]
    knockouts: list[dict]
    why_matched: list[str]
    why_not_matched: list[str]
    missing_skills: list[dict]
    partial_skills: list[dict]
    evidence: dict
    risks: list[str]
    recommendation: str
    qualifies: bool

    def label(self) -> str:
        return f"{LABEL}: {self.score:g}/100 (Confidence: {self.confidence.capitalize()})"


# ---------------------------------------------------------------- skills


def skill_credit(key: str, profile: CandidateProfile, taxonomy: Taxonomy) -> tuple[float, str]:
    """Evidence credit for one job skill: 1.0 resume+GitHub, 0.8 resume use, 0.7 GitHub only, 0.5 partial, 0."""
    s = profile.skills.get(key)
    if s is not None and s.level is not None:
        applied, high = s.resume == "applied", bool(s.gh_high)
        repos = f"{len(s.gh_high)} GitHub repo{'s' if len(s.gh_high) != 1 else ''}"
        if applied and high:
            return 1.0, f"used in resume experience/projects and {repos}"
        if applied:
            return 0.8, "used in resume experience/projects (no GitHub evidence)"
        if high:
            return 0.7, f"{repos} (not shown in resume experience)"
        basis = "listed on resume only" if s.resume == "listed" else "medium-strength GitHub evidence only"
        return 0.5, basis
    held = {k for k, v in profile.skills.items() if v.level in ("strong", "working")}
    adjacent = set(taxonomy.skills[key].adjacent) if key in taxonomy.skills else set()
    adjacent |= {k for k in held if k in taxonomy.skills and key in taxonomy.skills[k].adjacent}
    near = sorted(adjacent & held)
    if near:
        return 0.5, "adjacent skill: " + ", ".join(taxonomy.skills[k].name for k in near[:3])
    return 0.0, NOT_FOUND


def _weighted(items: list[tuple[float, float]]) -> float | None:
    total = sum(w for _, w in items)
    return sum(c * w for c, w in items) / total if total else None


def score_skills(job: JobView, profile: CandidateProfile, taxonomy: Taxonomy):
    required, preferred, evidence, missing, partial = [], [], {}, [], []
    for js in job.skills:
        if js.key is None:
            continue
        credit, basis = skill_credit(js.key, profile, taxonomy)
        (required if js.requirement == "required" else preferred).append((credit, js.weight))
        s = profile.skills.get(js.key)
        evidence[js.key] = {
            "name": js.name,
            "requirement": js.requirement,
            "credit": credit,
            "basis": basis,
            "fact_ids": s.fact_ids if s else [],
            "github": sorted(
                ({"repo": profile.repos[r].name, "url": profile.repos[r].url} for r in s.gh_high if r in profile.repos),
                key=lambda x: x["repo"],
            )
            if s
            else [],
        }
        if credit == 0:
            missing.append({"skill": js.key, "name": js.name, "requirement": js.requirement})
        elif credit < 0.7:
            partial.append({"skill": js.key, "name": js.name, "requirement": js.requirement, "reason": basis})
    req, pref = _weighted(required), _weighted(preferred)
    if req is None and pref is None:
        return Component(0.5, "The posting lists no recognisable skills. " + NOT_FOUND), evidence, missing, partial
    ratio = req * 0.75 + pref * 0.25 if req is not None and pref is not None else (req if req is not None else pref)
    n_req = len(required)
    have_req = sum(c >= 0.7 for c, _ in required)
    parts = [f"{have_req}/{n_req} required skills evidenced"] if n_req else []
    if preferred:
        parts.append(f"{sum(c >= 0.7 for c, _ in preferred)}/{len(preferred)} other skills evidenced")
    text = "; ".join(parts)
    return Component(ratio, text), evidence, missing, partial


# ---------------------------------------------------------------- other components


def score_experience(job: JobView, profile: CandidateProfile) -> Component:
    req, have = job.experience_years, profile.tech_years
    if req is None:
        return Component(
            0.7, f"No years requirement stated; you have {have:g} verified years ({profile.tech_years_source})."
        )
    ratio = 1.0 if have >= req else 0.8 if have >= 0.75 * req else 0.5 if have >= 0.5 * req else 0.2
    return Component(
        ratio,
        f"Requires {req:g}+ years; you have {have:g} verified years ({profile.tech_years_source}).",
        {"required": req, "verified": have, "fact_ids": profile.tech_years_fact_ids},
    )


def score_github(job: JobView, profile: CandidateProfile) -> Component:
    group = [s for s in job.skills if s.key and s.requirement == "required"] or [s for s in job.skills if s.key]
    if not group:
        return Component(0.5, "No skills to check against GitHub. " + NOT_FOUND)
    backing: set[str] = set()
    credits = []
    for s in group:
        ev = profile.skills.get(s.key)
        if ev and ev.gh_high:
            credits.append(1.0)
            backing |= ev.gh_high
        elif ev and ev.gh_medium:
            credits.append(0.6)
            backing |= ev.gh_medium
        else:
            credits.append(0.0)
    share = sum(credits) / len(credits)
    repos = [profile.repos[r] for r in backing if r in profile.repos]
    now = datetime.now(UTC)
    recent = [
        r for r in repos if r.pushed_at and (now - r.pushed_at.replace(tzinfo=r.pushed_at.tzinfo or UTC)).days < 180
    ]
    quality = [r for r in repos if (r.structure or {}).get("has_tests") or (r.structure or {}).get("has_ci")]
    ratio = min(1.0, 0.8 * share + (0.1 if recent else 0) + (0.1 if quality else 0))
    backed = sum(c > 0 for c in credits)
    text = (
        f"{backed}/{len(group)} {'required ' if group[0].requirement == 'required' else ''}skills have GitHub evidence"
    )
    if repos:
        text += f" across {len(repos)} repo{'s' if len(repos) != 1 else ''}"
        text += "; recently active" if recent else "; none pushed in the last 180 days"
        text += "; includes tests/CI" if quality else ""
    return Component(ratio, text, {"repos": sorted(r.name for r in repos)})


def _requested_certs(description: str) -> list[str]:
    return [name for name, rx in CERT_PATTERNS.items() if re.search(rx, description, re.I)]


def score_education(job: JobView, profile: CandidateProfile) -> Component:
    detail: dict = {}
    text = job.education
    if not text:
        degree, degree_text = 1.0, "No degree requirement stated."
    else:
        low = text.lower()
        req_level = 4 if re.search(r"\bph\.?d|doctorate", low) else 3 if re.search(r"\bmaster|\bm\.?sc?\b", low) else 2
        wants_tech = bool(TECH_FIELD_RX.search(text) or re.search(r"technical (field|discipline)|related field", low))
        equivalent = bool(re.search(r"equivalent|or (relevant|practical) experience", low))
        optional = bool(re.search(r"preferred|a plus|nice to have|ideally|desirable", low))
        met_field = [q for q in profile.qualifications if q.level >= req_level and (q.technical or not wants_tech)]
        met_level = [q for q in profile.qualifications if q.level >= req_level]
        l6 = [q for q in profile.qualifications if q.level6_diploma and q.technical]
        if met_field:
            degree, degree_text = 1.0, f"Meets the requirement: {met_field[0].name}."
        elif met_level or (l6 and req_level == 2):
            parts = []
            if met_level:
                parts.append(f"{met_level[0].name} meets the level but not the field")
            if l6 and req_level == 2:
                parts.append(f"{l6[0].name} is bachelor-level in a technical field but is a diploma, not a degree")
            degree, degree_text = 0.5, "; ".join(parts) + "."
        else:
            degree, degree_text = 0.0, "No qualification at the requested level. " + NOT_FOUND
        if equivalent and degree < 0.7 and (l6 or any(q.technical for q in profile.qualifications)):
            degree = 0.7
            degree_text += " The posting accepts equivalent experience."
        if optional and degree < 0.6:
            degree = 0.6
            degree_text += " The degree is preferred, not required."
        detail["requirement_quote"] = text
    requested = _requested_certs(job.description)
    held = " ".join(c["name"] for c in profile.certifications)
    matched = [c for c in requested if re.search(CERT_PATTERNS[c], held, re.I)]
    cert = len(matched) / len(requested) if requested else 1.0
    cert_text = (
        f"Certifications mentioned: {', '.join(requested)}; you hold {', '.join(matched) or 'none of them'}."
        if requested
        else "No certifications requested."
    )
    detail.update(requested_certs=requested, matched_certs=matched)
    return Component(degree * 0.6 + cert * 0.4, f"{degree_text} {cert_text}", detail)


def _sen_index(level: str | None) -> int | None:
    if level is None:
        return None
    level = SENIORITY_ALIASES.get(level, level)
    return SENIORITY_LEVELS.index(level) if level in SENIORITY_LEVELS else None


def score_role(job: JobView, profile: CandidateProfile, settings: UserSettings) -> Component:
    targets = set(settings.preferences.target_role_families)
    fam = job.role_family
    if fam in targets:
        f_ratio, f_text = 1.0, f"role family '{fam}' is one of your targets"
    elif fam and ADJACENT_FAMILIES.get(fam, set()) & targets:
        f_ratio, f_text = 0.6, f"role family '{fam}' is adjacent to your targets"
    else:
        f_ratio, f_text = 0.3, f"role family '{fam}' is outside your targets"
    idx, mine = _sen_index(job.seniority), profile.level_index
    if job.seniority is None:
        s_ratio, s_text = 0.7, "seniority not stated"
    elif job.seniority in settings.preferences.target_seniority:
        s_ratio, s_text = 1.0, f"'{job.seniority}' is a target seniority"
    elif idx is not None and idx - mine == 1:
        s_ratio, s_text = 0.5, f"'{job.seniority}' is one level above your verified level ({SENIORITY_LEVELS[mine]})"
    elif idx is not None and idx <= mine:
        s_ratio, s_text = 0.8, f"'{job.seniority}' is at or below your verified level ({SENIORITY_LEVELS[mine]})"
    else:
        s_ratio, s_text = 0.0, f"'{job.seniority}' is well above your verified level ({SENIORITY_LEVELS[mine]})"
    return Component(f_ratio * 0.6 + s_ratio * 0.4, f"{f_text.capitalize()}; {s_text}.")


def _in_cities(location: str | None, settings: UserSettings) -> bool:
    loc = (location or "").lower()
    return any(c.lower() in loc for c in settings.preferences.cities)


def score_location(job: JobView, settings: UserSettings) -> Component:
    prefs = settings.preferences
    ev = job.pk_evidence or NOT_FOUND
    if job.remote_type == "remote":
        if not prefs.accept_remote:
            return Component(0.0, "Remote role, but you turned off remote work in Settings.")
        if job.pk_eligibility == "eligible":
            return Component(1.0, f"Remote and open to Pakistan: {ev}")
        if job.pk_eligibility == "unknown":
            return Component(0.5, "Remote, but the posting does not say whether Pakistan is eligible. " + NOT_FOUND)
        return Component(0.0, f"Remote but not open to Pakistan: {ev}")
    if job.remote_type in ("onsite", "hybrid"):
        if job.remote_type == "hybrid" and not prefs.accept_hybrid:
            return Component(0.0, "Hybrid role, but you turned off hybrid work in Settings.")
        if _in_cities(job.location, settings):
            return Component(1.0, f"{job.remote_type.capitalize()} in {job.location}, one of your cities.")
        if job.pk_eligibility == "unknown":
            return Component(0.5, f"{job.remote_type.capitalize()}; city not confirmed. {ev}")
        return Component(0.0, f"{job.remote_type.capitalize()} in {job.location or 'an unstated place'}.")
    ratio = {"eligible": 0.8, "unknown": 0.4}.get(job.pk_eligibility, 0.0)
    return Component(ratio, f"Work arrangement not stated; Pakistan eligibility: {job.pk_eligibility} ({ev})")


def job_domains(job: JobView) -> dict[str, str]:
    """Domains the posting is clearly about: named in the title, or mentioned at least twice."""
    out = {}
    for domain, rx in DOMAIN_RX.items():
        hits = rx.findall(job.description)
        m = rx.search(job.title) or (rx.search(job.description) if len(hits) >= 2 else None)
        if m:
            out[domain] = m.group(0)
    return out


def score_domain(job: JobView, profile: CandidateProfile) -> Component:
    theirs = job_domains(job)
    shared = sorted(set(theirs) & set(profile.domains))
    if shared:
        d = shared[0]
        return Component(1.0, f"Domain overlap: the posting mentions '{theirs[d]}'; you have {profile.domains[d]}.")
    if theirs:
        return Component(0.5, f"Posting domain ({', '.join(sorted(theirs))}) is not one you have evidence for.")
    return Component(0.5, "No specific industry domain detected (neutral).")


# ---------------------------------------------------------------- knockouts, confidence, assembly


def knockouts(job: JobView, profile: CandidateProfile, settings: UserSettings) -> list[dict]:
    prefs, policy = settings.preferences, settings.policy
    out = []
    if job.pk_eligibility == "ineligible":
        out.append({"code": "pk_ineligible", "reason": f"Not open to candidates in Pakistan: {job.pk_evidence}"})
    elif job.pk_eligibility == "unknown" and policy.knockout_pk_eligibility_unknown:
        out.append({"code": "pk_unknown", "reason": "Pakistan eligibility unknown and your policy hides such jobs."})
    if (
        job.remote_type in ("onsite", "hybrid")
        and job.location
        and not _in_cities(job.location, settings)
        and not prefs.willing_to_relocate
        and job.pk_eligibility == "eligible"  # ineligible is reported above; unknown is not a knockout
    ):
        out.append(
            {
                "code": "location",
                "reason": f"{job.remote_type.capitalize()} in {job.location}, outside {' / '.join(prefs.cities)}.",
            }
        )
    quote = clearance_quote(job.description)
    if quote:
        out.append({"code": "clearance", "reason": f"Requires security clearance: '{quote}'"})
    if prefs.needs_visa_sponsorship and job.visa == "no sponsorship":
        out.append({"code": "visa", "reason": "You need visa sponsorship and the posting says it offers none."})
    idx = _sen_index(job.seniority)
    gap = policy.knockout_seniority_gap_levels
    if idx is not None and idx - profile.level_index >= gap:
        out.append(
            {
                "code": "seniority",
                "reason": f"'{job.seniority}' is {idx - profile.level_index} levels above your verified level "
                f"({SENIORITY_LEVELS[profile.level_index]}, from {profile.tech_years:g} years).",
            }
        )
    mult = policy.knockout_experience_multiple
    if job.experience_years is not None and job.experience_years > mult * profile.tech_years:
        out.append(
            {
                "code": "experience",
                "reason": f"Requires {job.experience_years:g}+ years; that is more than {mult:g}x your "
                f"{profile.tech_years:g} verified years.",
            }
        )
    if job.summary_only:
        out.append(
            {
                "code": "unconfirmed",
                "reason": f"Only a {len(job.description.strip())}-character summary of this posting is available, so "
                "requirements such as years of experience and seniority cannot be checked. Paste the full posting "
                "on the job page to score it properly.",
            }
        )
    return out


def confidence(job: JobView) -> tuple[str, int]:
    """Architecture step 3. The LLM agreement point is replaced by 'role family and seniority both classified'
    because extraction is deterministic."""
    mapped = [s for s in job.skills if s.key]
    pts = 0
    pts += 2 if len(job.description) > 1500 and len(mapped) >= 5 else 0
    pts += 1 if job.experience_years is not None else 0
    pts += 2 if job.pk_eligibility != "unknown" else 0
    pts += 1 if job.skills and len(mapped) / len(job.skills) >= 0.7 and len(mapped) >= 3 else 0
    pts += 1 if job.role_family and job.seniority else 0
    return ("high" if pts >= 6 else "medium" if pts >= 4 else "low"), pts


def recommendation(score: float, conf: str, kos: list[dict], threshold: float, missing_required: int) -> str:
    if kos:
        return "Hidden: " + kos[0]["reason"]
    if score >= 90 and conf == "high":
        return "Strong fit: prepare a tailored application."
    if score >= threshold:
        extra = f" First review the {missing_required} missing required skill(s)." if missing_required else ""
        return "Good fit: worth applying." + extra
    if score >= threshold - 15:
        return "Stretch: close the listed gaps before applying."
    return "Not recommended now."


def score_job(job: JobView, profile: CandidateProfile, settings: UserSettings, taxonomy: Taxonomy) -> MatchOutcome:
    w = settings.scoring_weights
    skills, evidence, missing, partial = score_skills(job, profile, taxonomy)
    comps = {
        "skills": (w.skills, skills),
        "experience": (w.experience, score_experience(job, profile)),
        "github_evidence": (w.github_evidence, score_github(job, profile)),
        "education_certs": (w.education_certs, score_education(job, profile)),
        "role_seniority": (w.role_seniority, score_role(job, profile, settings)),
        "location_remote": (w.location_remote, score_location(job, settings)),
        "domain": (w.domain, score_domain(job, profile)),
    }
    breakdown = {
        name: {
            "points": round(weight * c.ratio, 2),
            "max": weight,
            "ratio": round(c.ratio, 3),
            "explanation": c.explanation,
            **({"detail": c.detail} if c.detail else {}),
        }
        for name, (weight, c) in comps.items()
    }
    score = round(sum(b["points"] for b in breakdown.values()), 1)
    conf, pts = confidence(job)
    kos = knockouts(job, profile, settings)
    threshold = settings.preferences.min_fit_score

    strong = sorted(
        (e for e in evidence.values() if e["credit"] >= 0.8),
        key=lambda e: (e["requirement"] != "required", -e["credit"]),
    )
    why = [
        f"{name.replace('_', ' ').capitalize()}: {b['explanation']}"
        for name, b in breakdown.items()
        if b["ratio"] >= 0.8
    ]
    if strong:
        why.append("Best-evidenced skills: " + "; ".join(f"{e['name']} ({e['basis']})" for e in strong[:5]))
    why_not = [k["reason"] for k in kos]
    why_not += [
        f"{name.replace('_', ' ').capitalize()}: {b['explanation']}"
        for name, b in breakdown.items()
        if b["ratio"] < 0.5
    ]
    req_missing = [m for m in missing if m["requirement"] == "required"]
    if req_missing:
        why_not.append("Missing required skills: " + ", ".join(m["name"] for m in req_missing))

    risks = []
    if profile.training_only:
        risks.append(
            f"Your {profile.tech_years:g} years of technology experience come from a training programme; "
            "some employers do not count that as professional experience."
        )
    used = {f for e in evidence.values() if e["credit"] > 0 for f in e["fact_ids"]} | set(profile.tech_years_fact_ids)
    pending = used & profile.pending_fact_ids
    if pending:
        risks.append(
            f"{len(pending)} of the {len(used)} profile facts behind this score are still pending your review; "
            "the score assumes they are true."
        )
    if job.pk_eligibility == "unknown":
        risks.append("The posting does not say whether candidates in Pakistan can apply. " + NOT_FOUND)
    if job.posted_date and (datetime.now(UTC).date() - job.posted_date).days > 30:
        risks.append(f"Posted {job.posted_date.isoformat()}; it may already be filled.")
    if conf == "low":
        risks.append("Low confidence: the posting gives little detail, so the score may move a lot.")

    return MatchOutcome(
        score=score,
        confidence=conf,
        confidence_points=pts,
        components=breakdown,
        knockouts=kos,
        why_matched=why,
        why_not_matched=why_not,
        missing_skills=missing,
        partial_skills=partial,
        evidence=evidence,
        risks=risks,
        recommendation=recommendation(score, conf, kos, threshold, len(req_missing)),
        qualifies=not kos and score >= threshold,
    )


def rank_key(job: JobView, outcome: MatchOutcome) -> tuple:
    """Architecture ranking: score, skills, experience, github, location, posted date, salary known (all DESC)."""
    c = outcome.components
    return (
        -outcome.score,
        -c["skills"]["points"],
        -c["experience"]["points"],
        -c["github_evidence"]["points"],
        -c["location_remote"]["points"],
        -(job.posted_date.toordinal() if job.posted_date else 0),
        -int(job.salary_known),
    )
