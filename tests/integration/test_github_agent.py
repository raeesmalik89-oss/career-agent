import pytest
from sqlalchemy import select

from agents.github_agent import client as gh_client
from agents.github_agent.agent import GithubAnalyzerAgent, GithubAnalyzerInput
from agents.resume_agent.agent import DocumentInput, ResumeAnalyzerAgent, ResumeAnalyzerInput
from app.db.enums import SkillLevel
from app.db.models import GithubEvidence, GithubRepository, ProfileFact, Skill, UserSkill
from tests.conftest import login
from tests.fixtures.github import FULL_REPO, K8S_DEPLOYMENT, MACHINE, OWNER, STRANGER, make_repo
from tests.fixtures.resumes import PRIMARY_TXT

USERNAME = "ayesha-gh"


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """Three local repos: a full project by the owner (+ a server commit), a second Docker repo, a stranger's repo."""
    root = tmp_path / "src"
    paths = {
        "vitals-monitor": make_repo(root, "vitals-monitor", FULL_REPO, [OWNER, MACHINE]),
        "docker-lab": make_repo(
            root,
            "docker-lab",
            {
                "Dockerfile": "FROM nginx:1.27\n",
                "app.py": "import flask\n" + "x = 1\n" * 25,
                "deploy.yaml": K8S_DEPLOYMENT,
            },
        ),
        "borrowed": make_repo(
            root,
            "borrowed",
            {"Dockerfile": "FROM alpine\n", "main.tf": 'resource "aws_vpc" "v" {}\n'},
            [STRANGER, STRANGER, OWNER],
        ),
        "empty-fork": make_repo(root, "empty-fork", {"a.txt": "x\n"}),
    }
    infos = [
        gh_client.RepoInfo(
            name=n,
            url=f"https://github.com/{USERNAME}/{n}",
            clone_url=str(p),
            fork=n == "empty-fork",
            archived=False,
            stars=0,
            pushed_at="2026-09-01T00:00:00Z",
            default_branch="main",
            description=None,
        )
        for n, p in paths.items()
    ]
    monkeypatch.setattr(gh_client, "list_repos", lambda username, token=None: infos)
    return {n: str(p) for n, p in paths.items()}


def _run(db, user, repos):
    payload = GithubAnalyzerInput(
        user_id=user.id, username=USERNAME, extra_identities=[OWNER[1]], clone_url_override=repos
    )
    return GithubAnalyzerAgent().run(payload, db, user_id=user.id)


def _evidence(db, repo_name):
    rows = db.execute(
        select(GithubEvidence, Skill.canonical_name)
        .join(Skill, Skill.id == GithubEvidence.skill_id)
        .join(GithubRepository, GithubRepository.id == GithubEvidence.repo_id)
        .where(GithubRepository.name == repo_name)
    ).all()
    best: dict[str, str] = {}
    rank = {"low": 0, "medium": 1, "high": 2}
    for ev, key in rows:
        if rank[ev.strength.value] >= rank.get(best.get(key, "low"), 0):
            best[key] = ev.strength.value
    return best


def test_sync_collects_file_evidence(db, owner, repos):
    result = _run(db, owner, repos)
    assert result.ok, result.errors
    assert "skip_fork" in [a.type for a in result.actions]

    ev = _evidence(db, "vitals-monitor")
    for skill in (
        "docker",
        "docker_compose",
        "kubernetes",
        "terraform",
        "aws_ec2",
        "github_actions",
        "trivy",
        "fastapi",
        "isolation_forest",
        "pytest",
        "k8s_security",
    ):
        assert ev[skill] == "high", skill
    assert ev["helm"] == "low"  # only mentioned in the README: never enough to claim
    assert ev["kafka"] == "medium"  # only a dependency in requirements.txt
    assert "javascript" not in ev  # node_modules is skipped

    repo = db.scalars(select(GithubRepository).where(GithubRepository.name == "vitals-monitor")).one()
    assert repo.commit_stats["by_owner"] == 1 and repo.commit_stats["by_machine_identity"] == 1
    assert any("default identity" in f for f in repo.structure["flags"])
    assert repo.structure["has_tests"] and repo.structure["has_ci"] and repo.structure["readme"]["has_setup"]
    assert repo.readme_summary.startswith("Real-time vitals anomaly detection")


def test_evidence_from_mostly_foreign_commits_is_downgraded(db, owner, repos):
    _run(db, owner, repos)
    ev = _evidence(db, "borrowed")
    assert ev["docker"] == "medium" and ev["terraform"] == "medium"


def test_levels_combine_resume_and_github(db, owner, repos, tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text(PRIMARY_TXT, encoding="utf-8")
    ResumeAnalyzerAgent().run(
        ResumeAnalyzerInput(user_id=owner.id, documents=[DocumentInput(path=str(cv))]), db, user_id=owner.id
    )
    result = _run(db, owner, repos)
    levels = {
        s.canonical_name: us.level
        for us, s in db.execute(
            select(UserSkill, Skill).join(Skill, Skill.id == UserSkill.skill_id).where(UserSkill.user_id == owner.id)
        )
    }
    assert levels["kubernetes"] == SkillLevel.strong  # used in resume experience + high evidence in 2 own repos
    assert levels["docker"] == SkillLevel.working  # only *listed* on the resume; 2 repos alone are not enough
    assert levels["terraform"] == SkillLevel.working  # applied on resume, 1 own repo (the other is downgraded)
    assert levels["isolation_forest"] == SkillLevel.working  # GitHub only, one repo
    assert levels["datadog"] == SkillLevel.exposure  # resume-listed only
    assert "sre" not in levels  # only mentioned in a README: never creates a skill

    report = result.output
    names = {x["skill"] for x in report["resume_vs_github"]["resume_only"]}
    assert "datadog" in names and "docker" not in names
    assert "isolation_forest" in {x["skill"] for x in report["resume_vs_github"]["github_only"]}
    top = report["repositories"][0]
    assert top["name"] == "vitals-monitor" and top["has"]["has_tests"]


def test_project_claims_are_checked_against_the_repo(db, owner, repos):
    fact = ProfileFact(
        user_id=owner.id,
        fact_type="project",
        fact_key="vitals",
        source_type="resume",
        confidence="medium",
        source_ref={"sources": []},
        data={"name": "Vitals Monitor", "technologies": ["fastapi", "helm", "jenkins", "aws_ec2", "microservices"]},
    )
    db.add(fact)
    db.flush()
    _run(db, owner, repos)
    gh = db.get(ProfileFact, fact.id).data["github"]
    assert gh["repo"] == "vitals-monitor"
    assert gh["verified"] == ["aws_ec2", "fastapi"]
    assert gh["readme_only"] == ["helm"]
    assert gh["not_found_in_repo"] == ["jenkins"]
    assert gh["not_checkable"] == ["microservices"]


def test_resync_replaces_evidence(db, owner, repos):
    _run(db, owner, repos)
    first = db.scalars(select(GithubEvidence)).all()
    _run(db, owner, repos)
    assert len(db.scalars(select(GithubEvidence)).all()) == len(first)


def test_api_error_is_recorded(db, owner, monkeypatch):
    def boom(username, token=None):
        raise gh_client.GitHubError("GitHub API 403 for rate limit")

    monkeypatch.setattr(gh_client, "list_repos", boom)
    result = GithubAnalyzerAgent().run(GithubAnalyzerInput(user_id=owner.id, username=USERNAME), db, user_id=owner.id)
    assert not result.ok and result.errors[0].code == "github_api" and result.errors[0].retryable


def test_clone_refuses_other_hosts(tmp_path):
    with pytest.raises(gh_client.GitHubError, match="only github.com"):
        gh_client.sync_clone("https://evil.example.com/x.git", tmp_path / "x.git")


# ------------------------------------------------------------------ API


def test_github_api(client, owner, viewer, repos):
    headers = login(client, owner)
    assert client.post("/api/v1/github/sync", headers=headers, json={"username": "bad name"}).status_code == 422
    viewer_headers = login(client, viewer)
    assert client.post("/api/v1/github/sync", headers=viewer_headers, json={"username": USERNAME}).status_code == 403

    r = client.post("/api/v1/github/sync", headers=headers, json={"username": USERNAME})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["repositories"] == 3, r.text
    names = {x["name"] for x in client.get("/api/v1/github/repos", headers=headers).json()}
    assert names == {"vitals-monitor", "docker-lab", "borrowed"}
    report = client.get("/api/v1/github/intelligence", headers=headers).json()
    assert report["profile"]["username"] == USERNAME and report["evidence_map"]
