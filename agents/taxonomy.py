"""Skill taxonomy + deterministic skill matcher shared by the resume, GitHub, job and matching agents."""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy" / "skills.yaml"

# A skill token must not be glued to another word character (so "Git" does not match "GitHub").
_LEFT = r"(?<![A-Za-z0-9_+#])"
_RIGHT = r"(?![A-Za-z0-9_+#])"


@dataclass(frozen=True)
class SkillDef:
    key: str
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()
    adjacent: tuple[str, ...] = ()
    ambiguous: bool = False
    outdated: str | None = None


@dataclass
class SkillHit:
    key: str
    surface: str  # text exactly as it appeared
    start: int
    end: int


@dataclass
class Taxonomy:
    skills: dict[str, SkillDef]
    _patterns: list[tuple[re.Pattern, str, bool]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        for s in self.skills.values():
            for ref in (*s.implies, *s.adjacent):
                if ref not in self.skills:
                    raise ValueError(f"taxonomy: {s.key} references unknown skill {ref!r}")
            surfaces = sorted({s.name, *s.aliases}, key=len, reverse=True)
            alternation = "|".join(re.escape(x) for x in surfaces)
            flags = 0 if s.ambiguous else re.IGNORECASE
            self._patterns.append((re.compile(f"{_LEFT}(?:{alternation}){_RIGHT}", flags), s.key, s.ambiguous))

    def find(self, text: str, *, in_skills_list: bool = False) -> list[SkillHit]:
        """All non-overlapping skill mentions; longer surfaces win (e.g. 'Docker Compose' over 'Docker')."""
        hits: list[SkillHit] = []
        for pattern, key, ambiguous in self._patterns:
            if ambiguous and not in_skills_list:
                continue
            hits.extend(SkillHit(key, m.group(0), m.start(), m.end()) for m in pattern.finditer(text))
        hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
        kept: list[SkillHit] = []
        for h in hits:
            if kept and h.start < kept[-1].end:
                # Overlap: the longer surface wins. Nested skills come back through `implies`
                # (e.g. 'Azure DevOps' implies 'Azure').
                continue
            kept.append(h)
        return kept

    def implied(self, key: str) -> set[str]:
        """Transitive closure of `implies`."""
        out: set[str] = set()
        stack = list(self.skills[key].implies)
        while stack:
            k = stack.pop()
            if k not in out:
                out.add(k)
                stack.extend(self.skills[k].implies)
        return out


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    skills: dict[str, SkillDef] = {}
    for item in raw:
        key = item["key"]
        if key in skills:
            raise ValueError(f"taxonomy: duplicate key {key}")
        skills[key] = SkillDef(
            key=key,
            name=item["name"],
            category=item["category"],
            aliases=tuple(item.get("aliases", [])),
            implies=tuple(item.get("implies", [])),
            adjacent=tuple(item.get("adjacent", [])),
            ambiguous=bool(item.get("ambiguous", False)),
            outdated=item.get("outdated"),
        )
    return Taxonomy(skills)


@lru_cache
def get_taxonomy() -> Taxonomy:
    return load_taxonomy()
