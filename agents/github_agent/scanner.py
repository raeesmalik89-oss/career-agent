"""Analyse one bare repository: file evidence, structure, README quality and commit authorship."""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from agents.github_agent import client
from agents.github_agent.detectors import Evidence, detect_file
from agents.taxonomy import Taxonomy

SKIP_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    "vendor",
    "site-packages",
    ".ipynb_checkpoints",
    ".git",
    ".idea",
    ".vscode",
    "target",
    ".next",
    "coverage",
}
TEXT_EXT = {
    ".py",
    ".ipynb",
    ".sh",
    ".tf",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".cfg",
    ".txt",
    ".md",
    ".js",
    ".jsx",
    ".mjs",
    ".ts",
    ".tsx",
    ".sql",
    ".rego",
    ".hcl",
    ".ini",
    ".conf",
    ".dockerfile",
}
TEXT_NAMES = {"dockerfile", "jenkinsfile", "makefile", "mlproject", "procfile", ".gitlab-ci.yml"}
LANG_EXT = {
    ".py": "Python",
    ".ipynb": "Jupyter Notebook",
    ".sh": "Shell",
    ".tf": "HCL",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".css": "CSS",
    ".go": "Go",
    ".java": "Java",
    ".sql": "SQL",
    ".yml": "YAML",
    ".yaml": "YAML",
}
DEPLOY_RX = re.compile(
    r"docker(?:-| )compose up|kubectl apply|helm (?:install|upgrade)|terraform apply|"
    r"ansible-playbook|docker run|uvicorn |flask run|streamlit run",
    re.I,
)
MAX_FILES_READ = 1500


@dataclass
class RepoAnalysis:
    name: str
    evidence: list[Evidence] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    commit_stats: dict = field(default_factory=dict)
    readme_summary: str | None = None
    head_sha: str | None = None
    flags: list[str] = field(default_factory=list)


def _skip(path: str) -> bool:
    return any(part in SKIP_DIRS for part in path.split("/")[:-1])


def _is_text_candidate(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in TEXT_NAMES or name.startswith("dockerfile") or Path(name).suffix in TEXT_EXT


def _readme_stats(text: str) -> dict:
    headings = [h.strip("# ").lower() for h in re.findall(r"^#{1,3}\s+.+$", text, re.M)]
    words = len(re.findall(r"\w+", text))

    def has(*keys: str) -> bool:
        return any(any(k in h for k in keys) for h in headings)

    return {
        "words": words,
        "headings": len(headings),
        "has_setup": has("install", "setup", "getting started", "quick start", "quickstart", "run"),
        "has_usage": has("usage", "how to use", "example", "demo", "api"),
        "has_architecture": has("architecture", "design", "overview", "how it works") or "```mermaid" in text,
        "has_deploy_instructions": bool(DEPLOY_RX.search(text)),
        "has_screenshots": bool(re.search(r"!\[[^\]]*\]\(", text)),
    }


def _summary(text: str) -> str | None:
    """First real paragraph of the README (no badges/headings/HTML), max 400 chars."""
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b.startswith(("#", "!", "<", "[![", "|", "```", "---")):
            continue
        b = re.sub(r"\s+", " ", re.sub(r"[*_`>]", "", b))
        if len(b) > 40:
            return b[:400]
    return None


MACHINE_NAMES = {"ubuntu", "root", "ec2-user", "admin", "user", "vagrant", "azureuser", "debian", "centos", "pi"}


def classify_commit(c: dict, identities: set[str]) -> str:
    """owner | machine (a server's default identity such as 'Ubuntu') | other."""
    email, name = c["email"].lower(), c["author"].lower()
    if any(i and (i in email or i == name) for i in identities):
        return "owner"
    local = email.split("@")[0]
    if name in MACHINE_NAMES or local in MACHINE_NAMES or email.endswith((".internal", ".local")):
        return "machine"
    return "other"


def commit_stats(commits: list[dict], identities: set[str]) -> dict:
    if not commits:
        return {"total": 0}
    kinds = [classify_commit(c, identities) for c in commits]
    by_owner, by_machine = kinds.count("owner"), kinds.count("machine")
    days = Counter(c["date"][:10] for c in commits)
    dates = sorted(c["date"] for c in commits)
    return {
        "total": len(commits),
        "by_owner": by_owner,
        "by_machine_identity": by_machine,
        # Machine-identity commits in the owner's own repository count as the owner's, but are flagged.
        "owner_share": round((by_owner + by_machine) / len(commits), 2),
        "other_authors": sorted({c["author"] for c, k in zip(commits, kinds, strict=True) if k == "other"})[:10],
        "first": dates[0][:10],
        "last": dates[-1][:10],
        "active_days": len(days),
        "busiest_day_share": round(max(days.values()) / len(commits), 2),
    }


def analyze_repo(repo_path: Path, name: str, identities: set[str], taxonomy: Taxonomy) -> RepoAnalysis:
    ra = RepoAnalysis(name=name)
    tree = [e for e in client.list_tree(repo_path) if not _skip(e.path)]
    lang_bytes: Counter = Counter()
    for entry in tree:
        suffix = Path(entry.path).suffix.lower()
        if suffix in LANG_EXT:
            lang_bytes[LANG_EXT[suffix]] += entry.size
    texts = client.read_blobs(repo_path, [e for e in tree if _is_text_candidate(e.path)][:MAX_FILES_READ])
    readme_text = ""
    for path, text in texts.items():
        if path.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
            readme_text = text
            continue
        ra.evidence.extend(detect_file(path, text))

    # README mentions are low-strength docs evidence only.
    if readme_text:
        for key in sorted({h.key for h in taxonomy.find(readme_text)}):
            ra.evidence.append(Evidence(key, "docs", "README.md", "mentioned in README", "low"))
        ra.readme_summary = _summary(readme_text)

    paths = [e.path.lower() for e in tree]
    skills = {e.skill for e in ra.evidence if e.strength != "low"}
    ra.languages = dict(lang_bytes.most_common())
    ra.structure = {
        "files": len(tree),
        "top_dirs": sorted({p.split("/")[0] for p in paths if "/" in p})[:20],
        "has_readme": bool(readme_text),
        "readme": _readme_stats(readme_text) if readme_text else None,
        "has_tests": any(e.evidence_type == "test" for e in ra.evidence),
        "has_ci": any(e.evidence_type == "ci" for e in ra.evidence),
        "has_docker": "docker" in skills,
        "has_kubernetes": "kubernetes" in skills,
        "has_iac": bool(skills & {"terraform", "ansible", "pulumi", "cloudformation"}),
        "has_license": any(p.startswith("license") for p in paths),
        "has_env_example": any(p.endswith(".env.example") or p.endswith(".env.sample") for p in paths),
        "committed_env_file": any(p == ".env" or p.endswith("/.env") for p in paths),
    }
    commits = client.commit_log(repo_path)
    ra.commit_stats = commit_stats(commits, identities)
    ra.head_sha = commits[0]["sha"] if commits else None

    cs = ra.commit_stats
    if cs.get("total", 0) and cs["owner_share"] < 0.5:
        ra.flags.append("Most commits are by other authors; evidence from this repo is downgraded.")
    if cs.get("total", 0) <= 2 and len(tree) >= 30:
        ra.flags.append("Large repository with very few commits: history does not show incremental work.")
    if cs.get("by_machine_identity"):
        ra.flags.append(
            f"{cs['by_machine_identity']} commit(s) use a server's default identity (e.g. 'Ubuntu'), so GitHub does "
            "not credit them to you. Set git user.name and user.email on every server you commit from."
        )
    if not readme_text:
        ra.flags.append("No README: reviewers cannot tell what the project does.")
    if ra.structure["committed_env_file"]:
        ra.flags.append("A .env file is committed. Check it for secrets and rotate any that were exposed.")
    if not tree:
        ra.flags.append("Empty repository.")
    return ra


def downgrade_for_authorship(ra: RepoAnalysis) -> list[Evidence]:
    """High evidence counts as medium when the owner wrote less than half the commits."""
    share = ra.commit_stats.get("owner_share", 1.0) if ra.commit_stats.get("total") else 1.0
    if share >= 0.5:
        return ra.evidence
    return [
        Evidence(
            e.skill,
            e.evidence_type,
            e.path,
            e.detail + " (mostly others' commits)",
            "medium" if e.strength == "high" else e.strength,
        )
        for e in ra.evidence
    ]
