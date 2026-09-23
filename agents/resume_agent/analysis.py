"""Per-document resume analysis: skill mentions with context, and resume-quality findings."""

import re
from dataclasses import dataclass, field

from agents.resume_agent.extract import METRIC_RX, is_bullet, split_blocks, strip_bullet
from agents.resume_agent.parsing import Line, ParsedDocument
from agents.resume_agent.sections import Section
from agents.taxonomy import Taxonomy

APPLIED_SECTIONS = {"experience", "projects"}
LISTED_SECTIONS = {"skills", "summary", "header", "additional", "education", "certifications", "licenses"}
EXPECTED_SECTIONS = ("summary", "skills", "experience", "projects", "education")
WEAK_OPENERS = re.compile(
    r"^(?:responsible for|worked on|helped|assisted|involved in|duties included|participated in|tasked with)\b", re.I
)


@dataclass
class SkillMention:
    key: str
    surfaces: list[str] = field(default_factory=list)
    sections: set[str] = field(default_factory=set)
    lines: list[Line] = field(default_factory=list)
    skills_list_count: int = 0  # distinct skills-section lines naming this skill
    skills_list_surfaces: list[str] = field(default_factory=list)  # every mention inside the skills section
    implied_by: set[str] = field(default_factory=set)

    @property
    def is_duplicated(self) -> bool:
        """Named on two skills lines, or the same word repeated (seccomp + AppArmor on one line is not a duplicate)."""
        surfaces = self.skills_list_surfaces
        return self.skills_list_count > 1 or len(surfaces) != len(set(surfaces))

    @property
    def evidence(self) -> str:
        return "applied" if self.sections & APPLIED_SECTIONS else "listed"


def skill_mentions(sections: list[Section], taxonomy: Taxonomy) -> dict[str, SkillMention]:
    found: dict[str, SkillMention] = {}
    for s in sections:
        for ln in s.lines:
            for hit in taxonomy.find(ln.text, in_skills_list=s.name == "skills"):
                m = found.setdefault(hit.key, SkillMention(hit.key))
                m.surfaces.append(hit.surface)
                m.sections.add(s.name)
                if s.name == "skills":
                    m.skills_list_surfaces.append(hit.surface.lower())
                if ln not in m.lines:
                    m.lines.append(ln)
                    if s.name == "skills":
                        m.skills_list_count += 1
    # Implied skills inherit the sections of the skill that implies them (e.g. AKS -> Kubernetes, Azure).
    for key, m in list(found.items()):
        for implied in taxonomy.implied(key):
            im = found.setdefault(implied, SkillMention(implied))
            if not im.surfaces:
                im.implied_by.add(key)
            im.sections |= m.sections
            im.lines.extend(ln for ln in m.lines if ln not in im.lines)
    return found


def _bullets(sections: list[Section], names: set[str]) -> list[str]:
    out: list[str] = []
    for s in sections:
        if s.name in names:
            for b in split_blocks(s.lines):
                out.extend(b.bullet_texts())
    return out


def analyze_document(doc: ParsedDocument, sections: list[Section], mentions: dict[str, SkillMention],
                     taxonomy: Taxonomy) -> dict:  # fmt: skip
    names = {s.name for s in sections}
    weak: list[dict] = []

    summary = next((" ".join(ln.text for ln in s.lines) for s in sections if s.name == "summary"), None)
    if summary:
        words = len(summary.split())
        if words > 120:
            weak.append(
                {
                    "section": "summary",
                    "issue": f"Summary is long ({words} words).",
                    "suggestion": "Keep it to 3-4 lines (60-90 words) aimed at the target role.",
                }
            )
        elif words < 20:
            weak.append(
                {
                    "section": "summary",
                    "issue": f"Summary is very short ({words} words).",
                    "suggestion": "Say what you do, your strongest stack, and the role you want.",
                }
            )

    bullets = _bullets(sections, APPLIED_SECTIONS)
    with_metrics = [b for b in bullets if METRIC_RX.search(b)]
    if bullets and len(with_metrics) / len(bullets) < 0.3:
        weak.append(
            {
                "section": "experience/projects",
                "issue": f"Only {len(with_metrics)} of {len(bullets)} bullets contain a measurable result.",
                "suggestion": "Add real numbers you can defend (latency, uptime, time saved, counts). Never estimate.",
            }
        )
    weak_openers = [b for b in bullets if WEAK_OPENERS.match(b)]
    if weak_openers:
        weak.append(
            {
                "section": "experience/projects",
                "issue": f"{len(weak_openers)} bullets open with passive phrases ('responsible for', 'helped').",
                "suggestion": "Start with an action verb: Built, Automated, Reduced, Secured.",
            }
        )

    skills_listed = {k for k, m in mentions.items() if m.skills_list_count}
    if len(skills_listed) > 45:
        weak.append(
            {
                "section": "skills",
                "issue": f"{len(skills_listed)} skills listed.",
                "suggestion": "Long lists read as keyword stuffing; keep the skills you can discuss in depth.",
            }
        )
    if doc.layout == "two_column":
        weak.append(
            {
                "section": "layout",
                "issue": "Two-column layout.",
                "suggestion": "Many ATS parsers mix columns together; use a single-column version for portals.",
            }
        )
    if doc.pages > 2:
        weak.append({"section": "layout", "issue": f"{doc.pages} pages.", "suggestion": "Aim for 1-2 pages."})
    if any(re.search(r"●|○", ln.text) for ln in doc.lines):
        weak.append(
            {
                "section": "skills",
                "issue": "Skill-rating dots/bars.",
                "suggestion": "ATS systems cannot read self-ratings and recruiters discount them; remove them.",
            }
        )

    missing_sections = [s for s in EXPECTED_SECTIONS if s not in names]

    # Listed in the skills section but never used in any experience/project line.
    missing_evidence = sorted(
        (
            {"skill": k, "name": taxonomy.skills[k].name, "listed_in": sorted(m.sections)}
            for k, m in mentions.items()
            if m.surfaces and m.evidence == "listed" and "skills" in m.sections
        ),
        key=lambda d: d["name"].lower(),
    )
    duplicates = [
        {"skill": k, "name": taxonomy.skills[k].name, "count": len(m.skills_list_surfaces),
         "surfaces": sorted(set(m.surfaces))}
        for k, m in mentions.items() if m.is_duplicated
    ]  # fmt: skip
    outdated = [
        {"skill": k, "name": taxonomy.skills[k].name, "reason": taxonomy.skills[k].outdated}
        for k in mentions if taxonomy.skills[k].outdated and mentions[k].surfaces
    ]  # fmt: skip
    raw_bullets = [strip_bullet(ln.text) for ln in doc.lines if is_bullet(ln.text)]
    duplicate_lines = sorted({b for b in raw_bullets if raw_bullets.count(b) > 1})

    return {
        "layout": doc.layout,
        "pages": doc.pages,
        "warnings": doc.warnings,
        "sections_found": [s.name for s in sections],
        "missing_sections": missing_sections,
        "weak_sections": weak,
        "missing_evidence": missing_evidence,
        "duplicate_skills": sorted(duplicates, key=lambda d: -d["count"]),
        "duplicate_lines": duplicate_lines,
        "outdated_skills": outdated,
        "bullets_total": len(bullets),
        "bullets_with_metrics": len(with_metrics),
        "bullets_without_metrics_examples": [b for b in bullets if not METRIC_RX.search(b)][:5],
    }
