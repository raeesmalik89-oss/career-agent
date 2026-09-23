"""Resume Intelligence report built from stored facts and per-document analyses."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.taxonomy import Taxonomy
from app.db.enums import ResumeKind
from app.db.models import ProfileFact, ResumeProfile, ResumeVersion

EVIDENCE_NOT_FOUND = "Evidence not found."


def _ym(value: str | None, is_end: bool, today: date) -> int | None:
    """'2024-08' / '2024' / 'present' -> absolute month index."""
    if not value:
        return None
    if value == "present":
        return today.year * 12 + today.month - 1
    if len(value) >= 7:
        return int(value[:4]) * 12 + int(value[5:7]) - 1
    return int(value[:4]) * 12 + (11 if is_end else 0)


def _union_months(intervals: list[tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e + 1:
            if cur_e is not None:
                total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s + 1
    return total


def experience_summary(experiences: list[ProfileFact], today: date | None = None) -> dict:
    """Months per sector, counting overlapping entries once (grouped and itemised entries often overlap)."""
    today = today or date.today()
    buckets: dict[str, list[tuple[int, int]]] = {}
    for f in experiences:
        d = f.data
        s, e = _ym(d.get("start"), False, today), _ym(d.get("end"), True, today)
        if s is None or e is None or e < s:
            continue
        bucket = f"{d.get('sector', 'other')}{'_training' if d.get('is_training') else ''}"
        buckets.setdefault(bucket, []).append((s, e))
    months = {k: _union_months(v) for k, v in buckets.items()}
    tech = months.get("tech", 0) + months.get("tech_training", 0)
    return {
        "months_by_sector": months,
        "tech_months_total": tech,
        "tech_months_professional": months.get("tech", 0),
        "tech_months_training": months.get("tech_training", 0),
        "healthcare_months": months.get("healthcare", 0) + months.get("healthcare_training", 0),
        "note": "Overlapping entries are counted once. Training/internship months are reported separately "
        "and must be described as training, never as full-time employment.",
    }


def build_report(db: Session, user_id: uuid.UUID, taxonomy: Taxonomy) -> dict:
    profile = db.scalars(select(ResumeProfile).where(ResumeProfile.user_id == user_id)).first()
    facts = list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id)))
    versions = list(db.scalars(
        select(ResumeVersion).where(ResumeVersion.user_id == user_id).order_by(ResumeVersion.created_at)))  # fmt: skip
    live = [f for f in facts if f.review_status.value != "rejected"]
    by_type: dict[str, list[ProfileFact]] = {}
    for f in live:
        by_type.setdefault(f.fact_type.value, []).append(f)

    def fact_out(f: ProfileFact) -> dict:
        return {
            "id": str(f.id), "key": f.fact_key, "data": {k: v for k, v in f.data.items() if k != "conflicts"},
            "confidence": f.confidence.value, "review_status": f.review_status.value,
            "sources": [s.get("label") for s in f.source_ref.get("sources", [])],
        }  # fmt: skip

    # skills
    skills_by_category: dict[str, list[dict]] = {}
    for f in sorted(by_type.get("skill_claim", []), key=lambda f: f.data["name"].lower()):
        d = f.data
        sd = taxonomy.skills.get(d["skill"])
        skills_by_category.setdefault(d["category"], []).append({
            "skill": d["skill"], "name": d["name"], "evidence": d["evidence"],
            "sections": d.get("sections", []), "implied_by": d.get("implied_by", []),
            "outdated": sd.outdated if sd else None, "sources": len(f.source_ref.get("sources", [])),
            "fact_id": str(f.id),
        })  # fmt: skip
    missing_evidence = [
        {"skill": s["skill"], "name": s["name"], "detail": f"Listed but not used in any experience or project "
         f"line of any resume version. {EVIDENCE_NOT_FOUND} (GitHub evidence is checked in Milestone 3.)"}
        for items in skills_by_category.values() for s in items if s["evidence"] == "listed" and not s["implied_by"]
    ]  # fmt: skip

    resumes = [v for v in versions if v.kind == ResumeKind.source]
    certificates = [v for v in versions if v.kind == ResumeKind.certificate]
    primary = resumes[0] if resumes else None
    primary_analysis = (primary.parsed or {}).get("analysis", {}) if primary else {}

    conflicts = [
        {"fact_id": str(f.id), "fact_type": f.fact_type.value, "key": f.fact_key, "conflicts": f.data["conflicts"]}
        for f in facts if f.data.get("conflicts")
    ]  # fmt: skip

    # Achievements whose numbers appear in only one non-primary document deserve a second look.
    single_source_metrics = [
        {"fact_id": str(f.id), "text": f.data["text"], "metrics": f.data["metrics"],
         "only_in": f.source_ref["sources"][0].get("label")}
        for f in by_type.get("achievement", [])
        if len(f.source_ref.get("sources", [])) == 1 and primary is not None
        and f.source_ref["sources"][0].get("document_id") != str(primary.id)
    ]  # fmt: skip

    recommendations: list[str] = []
    cert_facts = by_type.get("certification", [])
    if cert_facts and "certifications" not in primary_analysis.get("sections_found", []):
        names = ", ".join(sorted({f.data.get("name") or "?" for f in cert_facts}))
        recommendations.append(f"Your primary resume has no Certifications section, but these were found: {names}.")
    title_conflicts = [c for c in conflicts if any(x["field"] == "title" for x in c["conflicts"])]
    if title_conflicts:
        recommendations.append(
            "Job titles differ between resume versions (see conflicts). Use one accurate title "
            "everywhere - recruiters and background checks compare them."
        )
    for v in resumes:
        if (v.parsed or {}).get("analysis", {}).get("layout") == "two_column":
            recommendations.append(f"'{v.label}' uses two columns; submit a single-column version to ATS portals.")
    if single_source_metrics:
        recommendations.append(
            f"{len(single_source_metrics)} measurable claim(s) appear in only one secondary "
            "version. Confirm each is accurate before it is reused in applications."
        )
    if missing_evidence:
        recommendations.append(
            f"{len(missing_evidence)} listed skill(s) have no project/experience evidence. "
            "Add a real example or be ready to explain them."
        )

    review = {s: sum(1 for f in facts if f.review_status.value == s) for s in ("pending", "verified", "rejected")}
    return {
        "profile": None
        if profile is None
        else {
            "name": profile.name,
            "location": profile.location,
            "contacts": profile.contacts,
            "links": profile.links,
            "summary": profile.summary,
        },
        "documents": [
            {
                "id": str(v.id),
                "label": v.label,
                "kind": v.kind.value,
                "format": v.format.value,
                "filename": v.original_filename,
                "is_primary": primary is not None and v.id == primary.id,
                "analysis": (v.parsed or {}).get("analysis"),
                "warnings": (v.parsed or {}).get("warnings", []),
            }
            for v in versions
        ],
        "experience_summary": experience_summary(by_type.get("experience", [])),
        "experience": [fact_out(f) for f in by_type.get("experience", [])],
        "education": [fact_out(f) for f in by_type.get("education", [])],
        "certifications": [fact_out(f) for f in cert_facts],
        "projects": [fact_out(f) for f in by_type.get("project", [])],
        "achievements": [fact_out(f) for f in by_type.get("achievement", [])],
        "preferences": [fact_out(f) for f in by_type.get("preference", [])],
        "skills_by_category": skills_by_category,
        "missing_evidence": missing_evidence,
        "duplicate_skills": primary_analysis.get("duplicate_skills", []),
        "outdated_skills": primary_analysis.get("outdated_skills", []),
        "weak_sections": primary_analysis.get("weak_sections", []),
        "missing_sections": primary_analysis.get("missing_sections", []),
        "single_source_metrics": single_source_metrics,
        "conflicts": conflicts,
        "recommendations": recommendations,
        "review": review,
        "certificate_documents": len(certificates),
    }
