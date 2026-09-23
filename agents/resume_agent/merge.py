"""Fact identity and cross-version merging.

The same fact usually appears in several resume versions with slightly different wording. We merge those
into one fact (keeping every source) and record a *conflict* whenever versions disagree on something that
matters (a job title, a date, a grade). Conflicts are never resolved automatically - the user decides.
"""

import hashlib
import re

from agents.resume_agent.extract import Extracted

_ORG_NOISE = {"plus", "and", "the", "pvt", "ltd", "limited", "inc", "llc", "co"}
_SYNONYMS = [
    (r"\bpg\b", "post graduate"),
    (r"\bba\b", "bachelor of arts"),
    (r"\bbs\b|\bbsc\b", "bachelor of science"),
    (r"\bms\b|\bmsc\b", "master of science"),
    (r"\bpharm-?d\b", "doctor of pharmacy"),
]
# Words whose presence/absence changes what a title claims. "Intern" vs "Trainee" is a real inconsistency.
ROLE_CRITICAL = {
    "intern", "trainee", "apprentice", "junior", "senior", "lead", "principal", "staff", "head", "chief",
    "manager", "director", "associate", "engineer", "developer", "analyst", "consultant", "architect",
    "pharmacist", "administrator", "specialist", "officer", "coordinator", "supervisor",
}  # fmt: skip
COMPARED_FIELDS = {
    "personal": ("value",),
    "preference": (),
    "experience": ("title", "start", "end"),
    "education": ("qualification", "date", "grade"),
    "certification": ("name", "issued", "credential_id"),
    "project": (),
    "achievement": (),
    "skill_claim": (),
}
LIST_FIELDS = ("responsibilities", "technologies", "highlights", "details", "context", "sections", "surfaces",
               "implied_by", "metrics")  # fmt: skip


def norm(s: str | None) -> str:
    s = (s or "").lower()
    for pattern, repl in _SYNONYMS:
        s = re.sub(pattern, repl, s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def tokens(s: str | None) -> set[str]:
    return set(norm(s).split())


def org_key(org: str | None) -> str:
    first = re.split(r"[,(|•–—]", org or "")[0]
    return " ".join(t for t in norm(first).split() if t not in _ORG_NOISE)


def _edu_level(q: str) -> str:
    n = norm(q)
    if "post graduate" in n:
        return "postgraduate"
    if re.search(r"doctor|phd", n):
        return "doctorate"
    if "master" in n or "mba" in n:
        return "master"
    if "bachelor" in n:
        return "bachelor"
    if "diploma" in n:
        return "diploma"
    return "other"


def fact_key(e: Extracted) -> str:
    d = e.data
    if e.kind in ("personal", "preference"):
        return d["field"]
    if e.kind == "experience":
        return f"{org_key(d.get('organization') or d.get('title'))}|{(d.get('start') or '')[:4]}"
    if e.kind == "education":
        year = (d.get("date") or "")[:4]
        return f"{year}|{_edu_level(d['qualification'])}" if year else norm(d["qualification"])[:120]
    if e.kind == "certification":
        return d.get("credential_id") or norm(d.get("name"))[:120]
    if e.kind == "project":
        return norm(d["name"])[:120]
    if e.kind == "achievement":
        return hashlib.sha1(norm(d["text"]).encode()).hexdigest()[:16]  # noqa: S324 - identity, not security
    if e.kind == "skill_claim":
        return d["skill"]
    raise ValueError(f"no key rule for {e.kind}")


_STOP = {"a", "the", "and", "with", "of", "for", "in", "on"}


def _containment(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a) - _STOP, tokens(b) - _STOP
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def same_project(a: str, b: str) -> bool:
    if min(len(tokens(a) - _STOP), len(tokens(b) - _STOP)) < 2:
        return norm(a) == norm(b)
    return _containment(a, b) >= 0.8


def same_entity(kind: str, existing: dict, new: dict) -> bool:
    """Fuzzy identity for facts whose wording varies between resume versions."""
    if kind == "project":
        return same_project(existing.get("name", ""), new.get("name", ""))
    if kind == "experience":
        years = {(existing.get("start") or "")[:4], (new.get("start") or "")[:4]}
        compatible_years = len(years - {""}) <= 1 and years != {""}  # equal, or one version has no dates
        orgs = org_key(existing.get("organization")), org_key(new.get("organization"))
        return compatible_years and _containment(*orgs) >= 0.8
    if kind == "education":
        if _edu_level(existing.get("qualification", "")) != _edu_level(new.get("qualification", "")):
            return False
        years = {(existing.get("date") or "")[:4], (new.get("date") or "")[:4]} - {""}
        return len(years) <= 1 and _containment(existing.get("qualification"), new.get("qualification")) >= 0.6
    return False


def compatible(field: str, a, b) -> bool:
    if a is None or b is None or a == b:
        return True
    if isinstance(a, str) and isinstance(b, str):
        if field in ("start", "end", "date", "issued"):
            return a.startswith(b) or b.startswith(a)  # "2021" vs "2021-07"
        na, nb = norm(a), norm(b)
        if na == nb:
            return True
        ta, tb = set(na.split()), set(nb.split())
        if (ta ^ tb) & ROLE_CRITICAL:
            return False
        return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.6
    return False


def merge_data(kind: str, old: dict, new: dict, old_label: str, new_label: str) -> tuple[dict, list[dict]]:
    """Merge `new` into `old`. Scalars keep the first value; disagreements become conflicts."""
    merged = dict(old)
    conflicts: list[dict] = []
    for key, value in new.items():
        if key == "conflicts":
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list) and key == "value":
            # personal list values (languages): union, one entry per language
            seen = {str(v.get("language", v)).lower() if isinstance(v, dict) else v for v in merged[key]}
            merged[key] = merged[key] + [
                v for v in value if (str(v.get("language", v)).lower() if isinstance(v, dict) else v) not in seen
            ]
        elif key in LIST_FIELDS and isinstance(value, list):
            existing = merged.get(key) or []
            merged[key] = existing + [v for v in value if v not in existing]
        elif merged.get(key) is None:
            merged[key] = value
        elif key == "evidence":
            merged[key] = "applied" if "applied" in (merged[key], value) else merged[key]
        elif key in COMPARED_FIELDS.get(kind, ()) and not compatible(key, merged[key], value):
            conflicts.append({"field": key, "old": merged[key], "new": value})
    if conflicts:
        merged["conflicts"] = _group_conflicts(merged.get("conflicts") or [], conflicts, old_label, new_label)
    return merged, conflicts


def _group_conflicts(known: list[dict], found: list[dict], old_label: str, new_label: str) -> list[dict]:
    """One entry per field: [{"field", "values": [{"value", "documents": [...]}]}]."""
    out = [dict(c, values=[dict(v, documents=list(v["documents"])) for v in c["values"]]) for c in known]
    for c in found:
        entry = next((e for e in out if e["field"] == c["field"]), None)
        if entry is None:
            entry = {"field": c["field"], "values": []}
            out.append(entry)
        for value, label in ((c["old"], old_label), (c["new"], new_label)):
            slot = next((v for v in entry["values"] if v["value"] == value), None)
            if slot is None:
                entry["values"].append({"value": value, "documents": [label]})
            elif label not in slot["documents"]:
                slot["documents"].append(label)
    return out
