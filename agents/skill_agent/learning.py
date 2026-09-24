"""Learning engine: curated guides (data/learning/*.yaml), concept maps, and the user's learning items.

Guide schema: key, title, why, explanation, cheatsheet[], commands[{cmd, what}], lab{goal, steps[], done_when},
troubleshooting[{problem, fix}], mini_project{title, brief, steps[], evidence}, resources[{title, url}],
concept_map{concept, components, interactions, production_use, devops_use, interview_traps, commands,
troubleshooting, related} where each list holds strings or {label, children[]}.

Completing a learning item never changes a skill level. Levels come only from evidence (resume use or code the
GitHub analyser finds), so each guide's mini-project says what evidence it produces.
"""

import re
import uuid
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.enums import LearningKind
from app.db.models import ConceptMap, LearningItem, Skill
from app.services import settings_service

GUIDE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "learning"
MAP_SECTIONS = [
    ("components", "Components"),
    ("interactions", "How they interact"),
    ("production_use", "Production use"),
    ("devops_use", "DevOps use"),
    ("interview_traps", "Interview traps"),
    ("commands", "Commands"),
    ("troubleshooting", "Troubleshooting"),
    ("related", "Related"),
]
MAX_DEPTH, MAX_NODES = 5, 80
# First word of every command in a guide or map must be a known tool (a typo or invented command fails validation).
COMMAND_ALLOWLIST = {
    "kubectl", "helm", "terraform", "docker", "gcloud", "az", "aws", "argocd", "git", "python", "pip", "pytest",
    "mvn", "gradle", "java", "jcmd", "npx", "npm", "sloth", "histogram_quantile", "sum", "rate", "datadog-agent",
    "ddtrace-run", "install-module", "get-azvm", "invoke-pester", "invoke-scriptanalyzer", "create", "select",
    "psql", "curl", "ansible-playbook", "kind", "minikube",
}  # fmt: skip
KINDS = [
    (LearningKind.explanation, "Understand it"),
    (LearningKind.cheatsheet, "Cheat sheet"),
    (LearningKind.commands, "Commands"),
    (LearningKind.lab, "Hands-on lab"),
    (LearningKind.troubleshooting, "Troubleshooting"),
    (LearningKind.mini_project, "Mini-project (produces evidence)"),
]


class GuideError(ValueError):
    pass


def _label(node) -> str:
    return node["label"] if isinstance(node, dict) else str(node)


def validate_concept_map(key: str, cmap: dict) -> None:
    if not isinstance(cmap, dict) or not cmap.get("concept"):
        raise GuideError(f"{key}: concept map needs a concept")
    nodes = 1

    def walk(items, depth: int) -> None:
        nonlocal nodes
        if depth > MAX_DEPTH:
            raise GuideError(f"{key}: concept map deeper than {MAX_DEPTH}")
        for it in items:
            nodes += 1
            if isinstance(it, dict):
                if "label" not in it:
                    raise GuideError(f"{key}: concept map node without a label")
                walk(it.get("children", []), depth + 1)
            elif not isinstance(it, str):
                raise GuideError(f"{key}: concept map nodes must be text or {{label, children}}")

    for section, _ in MAP_SECTIONS:
        items = cmap.get(section, [])
        if not isinstance(items, list):
            raise GuideError(f"{key}: concept map section {section} must be a list")
        nodes += 1
        walk(items, 2)
    if nodes > MAX_NODES:
        raise GuideError(f"{key}: concept map has {nodes} nodes (max {MAX_NODES})")
    for c in cmap.get("commands", []):
        _check_command(key, _label(c))


def _check_command(key: str, cmd: str) -> None:
    first = re.split(r"[\s(]", cmd.strip(), maxsplit=1)[0].lower()
    if first not in COMMAND_ALLOWLIST:
        raise GuideError(f"{key}: command {cmd!r} does not start with a known tool")


def validate_guide(g: dict) -> dict:
    required = {"key", "title", "why", "explanation", "cheatsheet", "commands", "lab", "troubleshooting",
                "mini_project", "resources", "concept_map"}  # fmt: skip
    missing = required - set(g)
    if missing:
        raise GuideError(f"{g.get('key', '?')}: missing {sorted(missing)}")
    if g["key"] not in get_taxonomy().skills:
        raise GuideError(f"{g['key']}: not a taxonomy skill")
    for c in g["commands"]:
        _check_command(g["key"], c["cmd"])
    for r in g["resources"]:
        if not str(r.get("url", "")).startswith("https://"):
            raise GuideError(f"{g['key']}: resource links must be https")
    if not g["mini_project"].get("evidence"):
        raise GuideError(f"{g['key']}: the mini-project must say what evidence it produces")
    validate_concept_map(g["key"], g["concept_map"])
    return g


def load_guides(directory: Path = GUIDE_DIR) -> dict[str, dict]:
    guides: dict[str, dict] = {}
    for path in sorted(directory.glob("*.yaml")):
        for g in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            validate_guide(g)
            if g["key"] in guides:
                raise GuideError(f"duplicate guide {g['key']}")
            guides[g["key"]] = g
    return guides


@lru_cache
def get_guides() -> dict[str, dict]:
    return load_guides()


# ---------------------------------------------------------------- rendering


def _mm(text: str) -> str:
    """Mermaid mindmap node text: drop characters that change node shape or break parsing."""
    return re.sub(r"[()\[\]{}<>\"`:;]", " ", text).strip() or "-"


def concept_map_mermaid(cmap: dict) -> str:
    lines = ["mindmap", f"  root(({_mm(cmap['concept'])}))"]

    def add(items, depth: int) -> None:
        for it in items:
            lines.append("  " * depth + _mm(_label(it)))
            if isinstance(it, dict):
                add(it.get("children", []), depth + 1)

    for section, title in MAP_SECTIONS:
        if cmap.get(section):
            lines.append("    " + _mm(title))
            add(cmap[section], 3)
    return "\n".join(lines)


def concept_map_markdown(cmap: dict) -> str:
    lines = [f"# {cmap['concept']}"]

    def add(items, depth: int) -> None:
        for it in items:
            lines.append("  " * depth + f"- {_label(it)}")
            if isinstance(it, dict):
                add(it.get("children", []), depth + 1)

    for section, title in MAP_SECTIONS:
        if cmap.get(section):
            lines.append(f"\n## {title}")
            add(cmap[section], 0)
    return "\n".join(lines)


def concept_map_tree(cmap: dict) -> dict:
    def node(it) -> dict:
        if isinstance(it, dict):
            return {"label": it["label"], "children": [node(c) for c in it.get("children", [])]}
        return {"label": str(it), "children": []}

    return {
        "label": cmap["concept"],
        "children": [
            {"label": title, "children": [node(i) for i in cmap.get(section, [])]}
            for section, title in MAP_SECTIONS
            if cmap.get(section)
        ],
    }


def section_markdown(g: dict, kind: LearningKind) -> str:
    if kind == LearningKind.explanation:
        return f"**Why it matters for you:** {g['why']}\n\n{g['explanation']}"
    if kind == LearningKind.cheatsheet:
        return "\n".join(f"- {c}" for c in g["cheatsheet"])
    if kind == LearningKind.commands:
        return "\n".join(f"- `{c['cmd']}` — {c['what']}" for c in g["commands"])
    if kind == LearningKind.lab:
        lab = g["lab"]
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(lab["steps"], 1))
        return f"**Goal:** {lab['goal']}\n\n{steps}\n\n**Done when:** {lab['done_when']}"
    if kind == LearningKind.troubleshooting:
        return "\n".join(f"- **{t['problem']}**: {t['fix']}" for t in g["troubleshooting"])
    mp = g["mini_project"]
    steps = "\n".join(f"- {s}" for s in mp.get("steps", []))
    return f"**{mp['title']}**\n\n{mp['brief']}\n\n{steps}\n\n**Evidence it produces:** {mp['evidence']}"


def fallback_guide(key: str) -> dict:
    """For skills without a curated guide: honest pointers, no invented content."""
    s = get_taxonomy().skills.get(key)
    name = s.name if s else key
    return {
        "key": key,
        "title": name,
        "curated": False,
        "why": f"{name} appears in jobs open to you and your profile has no strong evidence for it yet.",
        "explanation": f"No curated guide for {name} yet. Start with the official documentation and a small project.",
        "resources": [
            {
                "title": f"Search the official {name} documentation",
                "url": f"https://www.google.com/search?q={name.replace(' ', '+')}+official+documentation",
            }  # fmt: skip
        ],
        "mini_project": {
            "title": f"A small, public {name} project",
            "brief": f"Build something small that genuinely uses {name}, with a README explaining what you built "
            "and why.",
            "steps": [],
            "evidence": "Push it to GitHub and re-run the GitHub sync; the analyser records what it can detect.",
        },
    }


# ---------------------------------------------------------------- user state


def evidence_status(db: Session, user_id: uuid.UUID, key: str) -> dict:
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, user_id)
    profile = build_profile(db, user_id, taxonomy, settings)
    s = profile.skills.get(key)
    repos = sorted(profile.repos[r].name for r in (s.gh_high if s else set()) if r in profile.repos)
    return {
        "level": s.level if s else None,
        "resume": s.resume if s else None,
        "github_repos": repos,
        "note": "Levels change only with evidence: use it in a project you push to GitHub (then re-sync) or add it "
        "to your CV with a verified fact. Completing lessons alone never changes it.",
    }


def save_concept_map(db: Session, user_id: uuid.UUID, key: str, cmap: dict, day: date | None = None) -> ConceptMap:
    skill = db.scalars(select(Skill).where(Skill.canonical_name == key)).one()
    tree = concept_map_tree(cmap)
    latest = db.scalars(
        select(ConceptMap)
        .where(ConceptMap.user_id == user_id, ConceptMap.skill_id == skill.id)
        .order_by(ConceptMap.version.desc())
    ).first()
    if latest and latest.tree == tree:
        return latest
    row = ConceptMap(
        user_id=user_id,
        skill_id=skill.id,
        map_date=day or datetime.now(UTC).date(),
        tree=tree,
        mermaid=concept_map_mermaid(cmap),
        markdown=concept_map_markdown(cmap),
        version=(latest.version + 1) if latest else 1,
    )
    db.add(row)
    db.flush()
    return row


def plan_items(db: Session, user_id: uuid.UUID, keys: list[str]) -> list[LearningItem]:
    """Create the six learning items for each skill that has a curated guide (idempotent)."""
    guides = get_guides()
    ids = {s.canonical_name: s.id for s in db.scalars(select(Skill))}
    existing = {(i.skill_id, i.kind) for i in db.scalars(select(LearningItem).where(LearningItem.user_id == user_id))}
    created = []
    for key in keys:
        g = guides.get(key)
        if g is None or key not in ids:
            continue
        for kind, title in KINDS:
            if (ids[key], kind) in existing:
                continue
            item = LearningItem(
                user_id=user_id,
                skill_id=ids[key],
                kind=kind,
                title=f"{g['title']}: {title}",
                content_md=section_markdown(g, kind),
                status="todo",
            )
            db.add(item)
            created.append(item)
        save_concept_map(db, user_id, key, g["concept_map"])
    db.flush()
    return created
