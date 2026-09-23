"""Build throw-away local git repositories for GitHub-analyzer tests (no network)."""

import os
import subprocess
from pathlib import Path

OWNER = ("Ayesha Khan", "ayesha.khan@example.com")
MACHINE = ("Ubuntu", "ubuntu@ip-10-0-0-5.ec2.internal")
STRANGER = ("Someone Else", "someone@example.org")

K8S_DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      containers:
        - name: api
          image: example/api:1.0
          securityContext: {runAsNonRoot: true}
          readinessProbe: {httpGet: {path: /healthz, port: 8000}}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: api}
"""

WORKFLOW = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest -q
      - uses: aquasecurity/trivy-action@0.28.0
"""

APP_PY = """from fastapi import FastAPI
from sklearn.ensemble import IsolationForest
import pandas as pd

app = FastAPI()
model = IsolationForest(n_estimators=100)


@app.get("/score")
def score(value: float) -> dict:
    frame = pd.DataFrame({"v": [value]})
    return {"anomaly": int(model.fit_predict(frame)[0] == -1)}
""" + "\n".join(f"LIMIT_{i} = {i}" for i in range(5))

FULL_REPO = {
    "README.md": "# Vitals Monitor\n\nReal-time vitals anomaly detection service deployed with Helm on AWS EC2, "
    "following SRE practices.\n\n"
    "## Setup\n\n```\ndocker compose up\n```\n",
    "Dockerfile": "FROM python:3.12-slim AS build\nRUN pip install fastapi\nFROM python:3.12-slim\nUSER app\n",
    "docker-compose.yml": "services:\n  api: {build: .}\n  prometheus: {image: prom/prometheus}\n"
    "  grafana: {image: grafana/grafana}\n",
    "k8s/deployment.yaml": K8S_DEPLOYMENT,
    "infra/main.tf": 'provider "aws" {}\nresource "aws_instance" "api" {}\nresource "aws_s3_bucket" "models" {}\n',
    ".github/workflows/ci.yml": WORKFLOW,
    "app/main.py": APP_PY,
    "tests/test_main.py": "from app.main import app\n\n\ndef test_app():\n    assert app\n",
    "requirements.txt": "fastapi\nscikit-learn\nkafka-python\n",
    "node_modules/ignored/index.js": "console.log('vendored code is ignored')\n",
}


def _git(cwd: Path, *args: str, author: tuple[str, str] = OWNER) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
           "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1], "GIT_CONFIG_NOSYSTEM": "1"}  # fmt: skip
    subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd, env=env, check=True,  # noqa: S603, S607
                   capture_output=True)  # fmt: skip


def make_repo(root: Path, name: str, files: dict[str, str], authors: list[tuple[str, str]] | None = None) -> Path:
    """Create a repository; one commit per author in `authors` (default: a single owner commit)."""
    path = root / name
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    authors = authors or [OWNER]
    items = list(files.items())
    chunk = max(1, len(items) // len(authors))
    for i, author in enumerate(authors):
        part = items[i * chunk : None if i == len(authors) - 1 else (i + 1) * chunk] or [(f"note{i}.txt", "x\n")]
        for rel, content in part:
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", f"commit {i}", author=author)
    return path
