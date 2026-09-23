import pytest

from agents.github_agent.agent import match_project, repo_tokens
from agents.github_agent.client import GitHubError, validate_username
from agents.github_agent.detectors import detect_file
from agents.github_agent.scanner import classify_commit, commit_stats
from agents.skill_levels import level_for
from app.db.enums import SkillLevel
from tests.fixtures.github import APP_PY, K8S_DEPLOYMENT, WORKFLOW


def found(path: str, text: str) -> dict[str, str]:
    """skill -> best strength"""
    rank = {"low": 0, "medium": 1, "high": 2}
    out: dict[str, str] = {}
    for e in detect_file(path, text):
        if rank[e.strength] >= rank.get(out.get(e.skill, "low"), 0):
            out[e.skill] = e.strength
    return out


def test_dockerfile():
    got = found("Dockerfile", "FROM python:3.12 AS b\nFROM python:3.12-slim\nUSER app\n")
    assert got["docker"] == "high" and got["container_security"] == "medium"
    assert found("docs/Dockerfile.md", "FROM x") == {}  # not a Dockerfile


def test_compose_services_and_images():
    got = found("docker-compose.yml", "services:\n  db: {image: postgres:16}\n  kafka: {image: bitnami/kafka}\n")
    assert got["docker_compose"] == "high"
    assert got["postgresql"] == "medium" and got["kafka"] == "medium"  # image only: declared, not exercised


def test_kubernetes_manifests():
    got = found("k8s/app.yaml", K8S_DEPLOYMENT)
    assert got["kubernetes"] == "high" and got["k8s_security"] == "high" and got["auto_scaling"] == "high"
    assert "kubernetes" not in found("ci.yml", "name: x\nsteps: []\n")


def test_terraform_resources_and_providers():
    got = found("main.tf", 'provider "aws" {}\nresource "aws_eks_cluster" "c" {}\nresource "aws_iam_role" "r" {}\n')
    assert got["terraform"] == "high" and got["eks"] == "high" and got["iam"] == "high"
    assert got["aws"] == "medium"


def test_workflow_actions_and_commands():
    got = found(".github/workflows/ci.yml", WORKFLOW)
    assert got["github_actions"] == "high" and got["trivy"] == "high" and got["pytest"] == "high"
    assert found("docs/ci.yml", WORKFLOW).get("github_actions") is None  # only real workflow paths count


def test_python_imports_routes_and_models():
    got = found("app/main.py", APP_PY)
    assert got["python"] == "medium"  # under 20 code lines
    assert got["fastapi"] == "high" and got["isolation_forest"] == "high" and got["rest_api"] == "high"
    assert "pytest" in found("tests/test_api.py", "import pytest\n")


def test_requirements_are_medium_only():
    got = found("requirements.txt", "fastapi==0.1\nkafka-python\nunknown-lib\n")
    assert got == {"fastapi": "medium", "kafka": "medium"}


def test_ansible_playbook():
    assert found("site.yml", "- hosts: web\n  tasks:\n    - ping:\n")["ansible"] == "high"


def test_malformed_files_do_not_raise():
    assert found("broken.yaml", "apiVersion: v1\nkind: [unclosed") == {}


# ------------------------------------------------------------------ authorship


@pytest.mark.parametrize(
    "author, email, expected",
    [
        ("Ayesha Khan", "ayesha.khan@example.com", "owner"),
        ("ayesha-gh", "123+ayesha-gh@users.noreply.github.com", "owner"),
        ("Ubuntu", "ubuntu@ip-10-0-0-5.ec2.internal", "machine"),
        ("root", "root@localhost", "machine"),
        ("Someone Else", "someone@example.org", "other"),
    ],
)
def test_classify_commit(author, email, expected):
    assert classify_commit({"author": author, "email": email}, {"ayesha khan", "ayesha-gh"}) == expected


def test_commit_stats_counts_machine_identity_for_owner():
    commits = [{"author": "Ubuntu", "email": "ubuntu@x.internal", "date": "2026-01-01T00:00:00"},
               {"author": "Someone", "email": "s@example.org", "date": "2026-01-02T00:00:00"}]  # fmt: skip
    s = commit_stats(commits, {"ayesha"})
    assert s["by_machine_identity"] == 1 and s["owner_share"] == 0.5 and s["other_authors"] == ["Someone"]


# ------------------------------------------------------------------ project linking & levels


def test_repo_tokens():
    assert {"cardio", "care", "cardiocare", "aiops"} <= repo_tokens("CardioCare-AIOps")
    assert "lab" not in repo_tokens("k8s-cicd-lab")


@pytest.mark.parametrize(
    "project, expected",
    [
        ({"name": "CardioCare-AIOps"}, "CardioCare-AIOps"),
        ({"name": "MLOps Flask API"}, "MLOPs-flask-api"),
        ({"name": "ICU AIOps - Real-Time Sepsis Risk Prediction System"}, "ICU_Sepsis_Prediction-"),
        ({"name": "MLOps Pipeline: End-to-End Model Deployment"}, None),  # generic words only
        ({"name": "Anything", "context": ["see github.com/ayesha-gh/deployment-pipeline-lab"]},
         "deployment-pipeline-lab"),
        ({"name": "Anything", "github_repo": "CardioCare-AIOps"}, "CardioCare-AIOps"),
    ],
)  # fmt: skip
def test_match_project(project, expected):
    repos = ["CardioCare-AIOps", "MLOPs-flask-api", "ICU_Sepsis_Prediction-", "deployment-pipeline-lab"]
    assert match_project(project, repos, "ayesha-gh") == expected


@pytest.mark.parametrize(
    "resume, high, medium, expected",
    [
        ("applied", 2, 0, SkillLevel.strong),
        (None, 3, 0, SkillLevel.strong),
        ("listed", 2, 0, SkillLevel.working),
        (None, 1, 0, SkillLevel.working),
        ("applied", 0, 0, SkillLevel.working),
        ("listed", 0, 0, SkillLevel.exposure),
        (None, 0, 1, SkillLevel.exposure),
        (None, 0, 0, None),
    ],
)
def test_level_rules(resume, high, medium, expected):
    gh = {"high": set(range(high)), "medium": set(range(medium)), "low": set()}
    assert level_for(resume, gh) == expected


def test_username_validation():
    assert validate_username("raeesmalik89-oss") == "raeesmalik89-oss"
    for bad in ("../etc", "a b", "-leading", "x" * 40, ""):
        with pytest.raises(GitHubError):
            validate_username(bad)
