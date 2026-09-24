"""Curated interview question bank (data/interview/*.yaml), validated on load.

Entry schema:
  id:         stable, unique (used for spaced repetition)
  section:    core | scenario | design | hr
  skills:     taxonomy keys this question practises (empty for general / HR)
  difficulty: easy | medium | hard
  q:          the question
  tests:      what the interviewer is checking
  points:     key concepts, each [label, term, term, ...]; an answer covers a point if any term appears
  ideal:      model answer (shown only after the user has answered in a mock interview)
  mistakes:   common mistakes (list); optional red-flag regexes under `red_flags`
  follow_up:  the interviewer's likely next question
  spoken:     the same answer in simple spoken English
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from agents.taxonomy import get_taxonomy

BANK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "interview"
SECTIONS = {"core", "scenario", "design", "hr"}
DIFFICULTIES = {"easy", "medium", "hard"}


@dataclass(frozen=True)
class KeyPoint:
    label: str
    terms: tuple[str, ...]

    def covered_by(self, text: str) -> bool:
        return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}", text, re.I) for t in self.terms)


@dataclass(frozen=True)
class BankQuestion:
    id: str
    section: str
    skills: tuple[str, ...]
    difficulty: str
    q: str
    tests: str
    points: tuple[KeyPoint, ...]
    ideal: str
    mistakes: tuple[str, ...]
    follow_up: str
    spoken: str
    red_flags: tuple[tuple[str, str], ...] = field(default=())  # (regex, message)


def _entry(raw: dict, source: str) -> BankQuestion:
    missing = {"id", "section", "difficulty", "q", "tests", "points", "ideal", "mistakes", "follow_up", "spoken"} - set(
        raw
    )
    if missing:
        raise ValueError(f"{source}: {raw.get('id', '?')} is missing {sorted(missing)}")
    if raw["section"] not in SECTIONS or raw["difficulty"] not in DIFFICULTIES:
        raise ValueError(f"{source}: {raw['id']} has a bad section or difficulty")
    tax = get_taxonomy()
    unknown = [s for s in raw.get("skills", []) if s not in tax.skills]
    if unknown:
        raise ValueError(f"{source}: {raw['id']} references unknown skills {unknown}")
    points = tuple(KeyPoint(p[0], tuple(str(t) for t in p[1:]) or (p[0],)) for p in raw["points"])
    if len(points) < 2:
        raise ValueError(f"{source}: {raw['id']} needs at least 2 key points")
    return BankQuestion(
        id=raw["id"],
        section=raw["section"],
        skills=tuple(raw.get("skills", [])),
        difficulty=raw["difficulty"],
        q=raw["q"].strip(),
        tests=raw["tests"].strip(),
        points=points,
        ideal=raw["ideal"].strip(),
        mistakes=tuple(raw["mistakes"]),
        follow_up=raw["follow_up"].strip(),
        spoken=raw["spoken"].strip(),
        red_flags=tuple((r["pattern"], r["message"]) for r in raw.get("red_flags", [])),
    )


def load_bank(directory: Path = BANK_DIR) -> dict[str, BankQuestion]:
    bank: dict[str, BankQuestion] = {}
    for path in sorted(directory.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            q = _entry(raw, path.name)
            if q.id in bank:
                raise ValueError(f"duplicate question id {q.id} in {path.name}")
            bank[q.id] = q
    return bank


@lru_cache
def get_bank() -> dict[str, BankQuestion]:
    return load_bank()
