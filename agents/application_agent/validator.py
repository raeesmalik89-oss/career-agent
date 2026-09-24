"""Claim-level validation of an application package (the Compliance agent), fully deterministic.

For every generated item:
  unsupported     a cited fact is missing or rejected, a technology is named that the user has no evidence for,
                  or a number appears that is in none of the cited facts (and was not derived from them).
                  Unsupported items block approval: "Evidence not found."
  needs_approval  relies on facts still pending review, on facts with unresolved conflicts, contains a
                  [placeholder] for the user's own words, or was written by the user and names an unevidenced
                  technology (their call, but it is flagged).
  valid           everything checks out against verified facts.
"""

import json
import re
from dataclasses import dataclass, field

from agents.application_agent.package import PLACEHOLDER_RX
from agents.match_agent.profile import CandidateProfile
from agents.taxonomy import Taxonomy
from app.db.models import ProfileFact

NUMBER_RX = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?")
# Numbers that are formatting, not claims: small list indices, years in dates are checked via the facts anyway.
TRIVIAL = {"0", "1"}


@dataclass
class Verdict:
    status: str = "valid"  # valid | needs_approval | unsupported
    notes: list[str] = field(default_factory=list)

    def worse(self, status: str, note: str) -> None:
        order = {"valid": 0, "needs_approval": 1, "unsupported": 2}
        if order[status] > order[self.status]:
            self.status = status
        if note not in self.notes:
            self.notes.append(note)


def _norm_number(n: str) -> str:
    return n.replace(",", "").rstrip("%")


def validate_item(
    item: dict,
    facts: dict[str, ProfileFact],
    profile: CandidateProfile,
    taxonomy: Taxonomy,
    *,
    skills_list: bool = False,
) -> Verdict:
    v = Verdict()
    text = item.get("text") or ""
    user = item.get("user_written", False)
    cited = []
    for fid in item.get("fact_ids", []):
        f = facts.get(fid)
        if f is None:
            v.worse("unsupported", "cites a fact that does not exist. Evidence not found.")
        elif f.review_status.value == "rejected":
            v.worse("unsupported", "cites a fact you rejected.")
        else:
            cited.append(f)
            if f.review_status.value == "pending":
                v.worse("needs_approval", "relies on a fact you have not verified yet.")
            if f.data.get("conflicts"):
                v.worse("needs_approval", "relies on a fact whose documents disagree; resolve the conflict.")

    if PLACEHOLDER_RX.search(text):
        v.worse("needs_approval", "needs your own words (replace the [bracketed] text).")

    for hit in taxonomy.find(text, in_skills_list=skills_list):
        s = profile.skills.get(hit.key)
        if s is None or s.level is None:
            status = "needs_approval" if user else "unsupported"
            v.worse(status, f"mentions {hit.surface}, which your profile has no evidence for. Evidence not found.")

    if not user:
        source_text = " ".join(json.dumps(f.data, ensure_ascii=False) for f in cited)
        known = {_norm_number(n) for n in NUMBER_RX.findall(source_text)} | {
            _norm_number(d) for d in item.get("derived", [])
        }
        for n in NUMBER_RX.findall(text):
            if _norm_number(n) not in known and _norm_number(n) not in TRIVIAL:
                v.worse("unsupported", f"the number {n} is not in the cited facts. Evidence not found.")
    return v


def validate_resume(resume: dict, facts: dict[str, ProfileFact], profile: CandidateProfile, taxonomy: Taxonomy) -> dict:
    """Returns {"items": [{"path", "text", "status", "notes"}], "counts": {...}} for every line of the resume."""
    results = []

    def check(path: str, item: dict, skills_list: bool = False):
        v = validate_item(item, facts, profile, taxonomy, skills_list=skills_list)
        results.append({"path": path, "text": item["text"][:200], "status": v.status, "notes": v.notes})

    for key, item in resume["header"].items():
        check(f"header.{key}", item)
    for gi, g in enumerate(resume["skills"]):
        for si, s in enumerate(g["items"]):
            check(f"skills.{gi}.{si}", s, skills_list=True)
    for ei, e in enumerate(resume["experience"]):
        check(f"experience.{ei}", {"text": f"{e['title']} {e['organization']}", "fact_ids": e["fact_ids"]})
        for bi, b in enumerate(e["bullets"]):
            check(f"experience.{ei}.bullets.{bi}", b)
    for pi, p in enumerate(resume["projects"]):
        check(f"projects.{pi}", {"text": " ".join([p["name"], *p["technologies"]]), "fact_ids": p["fact_ids"]},
              skills_list=True)  # fmt: skip
        for bi, b in enumerate(p["bullets"]):
            check(f"projects.{pi}.bullets.{bi}", b)
    for i, e in enumerate(resume["education"]):
        check(f"education.{i}", {"text": f"{e['qualification']} {e['institution']}", "fact_ids": e["fact_ids"]})
    for i, c in enumerate(resume["certifications"]):
        check(f"certifications.{i}", {"text": c["name"], "fact_ids": c["fact_ids"]})
    if resume.get("summary"):
        # The summary is the user's own CV text: skills in it must still be evidenced, numbers are theirs.
        check("summary", {"text": resume["summary"]["text"], "fact_ids": [], "user_written": True})
    counts = {s: sum(r["status"] == s for r in results) for s in ("valid", "needs_approval", "unsupported")}
    return {"items": results, "counts": counts}
