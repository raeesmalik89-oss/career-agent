"""Automatic, explainable scoring of a practice answer (docs/ARCHITECTURE.md section 7, rubric weights).

  accuracy       40  key concepts covered (the concepts that define a correct answer)
  completeness   25  all concepts covered, and enough detail relative to the model answer
  structure      15  STAR for behavioural questions; ordered steps / clear reasoning for technical ones
  depth          10  reasons and trade-offs ("because", "trade-off", "instead", "depends", ...)
  communication  10  answer length and sentence length suited to speaking

This checks concept coverage and form. It cannot tell whether a sentence is true, so the report says so.
"""

import re
from dataclasses import dataclass, field

from agents.interview_agent.bank import KeyPoint

WEIGHTS = {"accuracy": 40, "completeness": 25, "structure": 15, "depth": 10, "communication": 10}
DISCLAIMER = (
    "Automatic feedback based on which key concepts your answer covers and how it is structured. "
    "It cannot judge whether each statement is correct, so compare with the model answer."
)
STAR = {
    "situation": r"\b(when|at (my|the)|during|situation|"
    r"in (my|the) (training|lab|project|hospital|pharmacy|role|job))\b",
    "task": r"\b(i (had|needed|was asked|was responsible)|my (task|goal|job|role) was|the goal|needed to)\b",
    "action": r"\b(i (built|created|set up|configured|wrote|designed|deployed|fixed|added|used|decided|led|"
    r"automated|investigated|checked|moved|changed|implemented|talked|explained|learned))\b",
    "result": r"\b(as a result|result(ed)?|so that|which (cut|reduced|improved|saved)|reduced|improved|saved|"
    r"now|in the end|outcome|learned)\b|\d+\s?%",
}
STEP_WORDS = r"\b(first(ly)?|second(ly)?|then|next|after that|finally|step \d|1\.|2\.|because|so|therefore)\b"
DEPTH_WORDS = (
    r"\b(because|trade-?offs?|however|instead|depends|downside|risk|cost|latency|scal(e|ing|ability)|"
    r"alternative|compared (to|with)|why|limitation|would (not|rather)|in production)\b"
)


@dataclass
class Evaluation:
    score: int
    rubric: dict[str, dict] = field(default_factory=dict)
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9'+#./-]+", text)


def evaluate(
    answer: str,
    points: list[KeyPoint],
    *,
    ideal: str,
    behavioural: bool,
    red_flags: list[tuple[str, str]] | tuple = (),
    anchored: bool = False,
) -> Evaluation:
    """anchored=True: the first key point is the subject of the question (e.g. the exact CV number asked about);
    an answer that never addresses it is capped, however many other concepts it mentions."""
    text = answer.strip()
    words = _words(text)
    covered = [p for p in points if p.covered_by(text)]
    missing = [p.label for p in points if p not in covered]
    core = points[: max(2, (len(points) + 1) // 2)]  # the first half of the points are the essential ones
    core_cov = sum(p in covered for p in core) / len(core)
    all_cov = len(covered) / len(points)
    ideal_len = max(len(_words(ideal)), 30)
    length_ratio = min(1.0, len(words) / (0.5 * ideal_len))

    if behavioural:
        star_hits = {k: bool(re.search(rx, text, re.I)) for k, rx in STAR.items()}
        structure = sum(star_hits.values()) / 4
        structure_note = "STAR parts found: " + ", ".join(k for k, v in star_hits.items() if v) if any(
            star_hits.values()) else "no Situation / Task / Action / Result structure found"  # fmt: skip
    else:
        steps = len(re.findall(STEP_WORDS, text, re.I)) + text.count("\n-") + text.count("\n*")
        structure = min(1.0, steps / 3)
        structure_note = f"{steps} ordering/reasoning signal(s) (first, then, because, lists)"

    depth_hits = len(set(m.group(0).lower() for m in re.finditer(DEPTH_WORDS, text, re.I)))
    depth = min(1.0, depth_hits / 3)

    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(_words(s)) >= 2]
    avg = len(words) / max(len(sentences), 1)
    comm = 1.0
    notes = []
    if len(words) < 25:
        comm -= 0.5
        notes.append("very short")
    elif len(words) > 400:
        comm -= 0.4
        notes.append("too long to say out loud (aim for 1-2 minutes)")
    if avg > 35:
        comm -= 0.3
        notes.append("long sentences; split them")
    comm = max(0.0, comm)

    parts = {
        "accuracy": (core_cov, f"{sum(p in covered for p in core)}/{len(core)} essential concepts covered"),
        "completeness": (
            0.7 * all_cov + 0.3 * length_ratio,
            f"{len(covered)}/{len(points)} concepts; {len(words)} words vs ~{ideal_len} in the model answer",
        ),  # fmt: skip
        "structure": (structure, structure_note),
        "depth": (depth, f"{depth_hits} reasoning/trade-off signal(s)"),
        "communication": (comm, "; ".join(notes) or "good length for a spoken answer"),
    }
    rubric = {
        k: {"points": round(WEIGHTS[k] * ratio, 1), "max": WEIGHTS[k], "note": note}
        for k, (ratio, note) in parts.items()
    }
    score = round(sum(r["points"] for r in rubric.values()))
    off_topic = anchored and points and points[0] not in covered and bool(text)
    if off_topic:
        score = min(score, 40)

    mistakes = []
    if not text:
        mistakes.append("No answer given.")
    elif len(words) < 25:
        mistakes.append("Too short: interviewers expect a few sentences with an example.")
    for pattern, message in red_flags:
        if re.search(pattern, text, re.I):
            mistakes.append(message)
    if behavioural and structure < 0.5 and text:
        mistakes.append("Tell it as a story: situation, what you had to do, what you did, and the result.")
    if not behavioural and depth == 0 and text:
        mistakes.append("Say why: give a reason or a trade-off, not only what.")
    if off_topic:
        mistakes.insert(0, f"Your answer does not address the question itself ({points[0].label}).")
    if re.search(r"\b(i don'?t know|no idea|not sure)\b", text, re.I) and len(words) < 40:
        mistakes.append("If unsure, reason out loud from what you do know instead of stopping.")
    return Evaluation(
        score=score, rubric=rubric, covered=[p.label for p in covered], missing=missing, mistakes=mistakes
    )
