"""Split parsed lines into canonical resume sections."""

import re
from dataclasses import dataclass, field

from agents.resume_agent.parsing import Line

HEADINGS: dict[str, tuple[str, ...]] = {
    "summary": (
        "professional summary", "summary", "profile", "professional profile", "about", "about me",
        "objective", "career objective", "headline", "career summary",
    ),
    "skills": (
        "technical skills", "skills", "core skills", "key skills", "technologies", "tech stack",
        "competencies", "core competencies", "tools", "skills & tools", "technical expertise",
    ),
    "experience": (
        "experience", "professional experience", "work experience", "employment", "employment history",
        "career history", "internships", "work history", "relevant experience",
    ),
    "projects": ("projects", "key projects", "selected projects", "personal projects", "portfolio projects"),
    "education": (
        "education", "academic background", "qualifications", "education & training", "academics",
        "education & certification", "education & certifications", "education and certifications",
    ),
    "certifications": (
        "certifications", "certificates", "licenses & certifications", "licences & certifications",
        "courses", "training", "certifications & training",
    ),
    "languages": ("languages",),
    "contact": ("contact", "contact details", "contact information"),
    "availability": ("availability",),
    "achievements": ("achievements", "awards", "accomplishments", "honours", "honors"),
    "licenses": ("licenses", "licences", "professional license", "professional licence", "licensure"),
    "additional": ("additional", "additional information", "interests", "other", "extras"),
}  # fmt: skip
_ALIAS = {alias: name for name, aliases in HEADINGS.items() for alias in aliases}
_STRIP = re.compile(r"^[\s#=*_\-:|]+|[\s#=*_\-:|]+$")


@dataclass
class Section:
    name: str  # canonical name, or "header" for text before the first heading
    heading: str | None
    lines: list[Line] = field(default_factory=list)


def heading_name(text: str, allow_generic: bool = False) -> str | None:
    t = _STRIP.sub("", text).lower()
    t = re.sub(r"\s+", " ", t)
    if t in _ALIAS:
        return _ALIAS[t]
    raw = _STRIP.sub("", text)
    # Unknown ALL-CAPS headings still start a section so their content is not merged into the previous one.
    if allow_generic and raw.isupper() and 2 <= len(raw.split()) <= 8 and not re.search(r"[@\d]", raw):
        if re.search(r"licen[cs]", t):
            return "licenses"
        if re.search(r"certific", t):
            return "certifications"
        return "additional"
    return None


def split_sections(lines: list[Line], column_breaks: set[int] = frozenset()) -> list[Section]:
    """Sections in reading order. A column break starts a fresh untitled section (e.g. a sidebar)."""
    sections = [Section("header", None)]
    seen_heading = False  # generic ALL-CAPS headings only count after a real one (the name line is all caps too)
    for i, line in enumerate(lines):
        if i in column_breaks and i > 0:
            sections.append(Section("header", None))
            seen_heading = False
        name = heading_name(line.text, allow_generic=seen_heading) if len(line.text) <= 60 else None
        if name:
            seen_heading = True
            sections.append(Section(name, line.text))
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if s.lines or s.name != "header"]


def section_of(sections: list[Section]) -> dict[int, str]:
    """Map line start offset -> canonical section name."""
    return {ln.start: s.name for s in sections for ln in s.lines}
