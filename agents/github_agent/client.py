"""Read-only access to public GitHub data.

Repository listing uses the REST API (1-2 calls). Contents and history come from a bare, partial clone
(`--filter=blob:limit=1m`), so large model files are never downloaded and nothing is checked out or executed.
"""

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

NAME_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")  # GitHub username rules
REPO_RX = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
API = "https://api.github.com"
MAX_BLOB = 1024 * 1024


class GitHubError(RuntimeError):
    pass


@dataclass
class RepoInfo:
    name: str
    url: str
    clone_url: str
    fork: bool
    archived: bool
    stars: int
    pushed_at: str | None
    default_branch: str | None
    description: str | None


def validate_username(username: str) -> str:
    if not NAME_RX.match(username or ""):
        raise GitHubError(f"invalid GitHub username {username!r}")
    return username


def _get_json(url: str, token: str | None) -> object:
    if not url.startswith(API + "/"):
        raise GitHubError("refusing to call a non-GitHub URL")  # SSRF guard: fixed host only
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "career-agent"}
    req = urllib.request.Request(url, headers=headers)  # noqa: S310 - host fixed above
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - scheme/host checked above
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise GitHubError(f"GitHub API {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise GitHubError(f"GitHub API unreachable: {exc.reason}") from exc


def list_repos(username: str, token: str | None = None) -> list[RepoInfo]:
    validate_username(username)
    repos: list[RepoInfo] = []
    for page in range(1, 6):
        data = _get_json(f"{API}/users/{username}/repos?per_page=100&type=owner&sort=pushed&page={page}", token)
        if not isinstance(data, list) or not data:
            break
        for r in data:
            if not REPO_RX.match(r["name"]):
                continue
            repos.append(
                RepoInfo(
                    name=r["name"],
                    url=r["html_url"],
                    clone_url=f"https://github.com/{username}/{r['name']}.git",
                    fork=bool(r.get("fork")),
                    archived=bool(r.get("archived")),
                    stars=int(r.get("stargazers_count", 0)),
                    pushed_at=r.get("pushed_at"),
                    default_branch=r.get("default_branch"),
                    description=r.get("description"),
                )
            )
        if len(data) < 100:
            break
    return repos


def _git_raw(args: list[str], cwd: Path | None = None, timeout: int = 300, stdin: bytes | None = None) -> bytes:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # never prompt for credentials
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",  # reading a filtered-out blob must not download it
    }
    cmd = ["git", "-c", "protocol.file.allow=user", "-c", "core.hooksPath=/dev/null", *args]
    try:
        out = subprocess.run(  # noqa: S603 - fixed binary, validated arguments, no shell
            cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=True, input=stdin
        )
    except subprocess.CalledProcessError as exc:
        raise GitHubError(f"git {args[0]} failed: {exc.stderr.decode(errors='replace')[:300]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHubError(f"git {args[0]} timed out") from exc
    return out.stdout


def _git(args: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    return _git_raw(args, cwd, timeout).decode("utf-8", errors="replace")


def sync_clone(clone_url: str, dest: Path) -> Path:
    """Create or update a bare partial clone at `dest`."""
    if not (clone_url.startswith("https://github.com/") or Path(clone_url).exists()):
        raise GitHubError("only github.com (or local test) repositories can be cloned")
    if (dest / "HEAD").exists():
        _git(["fetch", "--prune", "--filter=blob:limit=1m", "origin", "+refs/heads/*:refs/heads/*"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--bare", "--filter=blob:limit=1m", "--no-tags", clone_url, str(dest)])
    return dest


@dataclass
class TreeEntry:
    path: str
    size: int
    sha: str


def list_tree(repo: Path) -> list[TreeEntry]:
    try:
        out = _git(["ls-tree", "-r", "-l", "--full-tree", "HEAD"], cwd=repo)
    except GitHubError:
        return []  # empty repository
    entries = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 4 and parts[1] == "blob":
            size = int(parts[3]) if parts[3].isdigit() else 0
            entries.append(TreeEntry(path, size, parts[2]))
    return entries


def read_blobs(repo: Path, entries: list[TreeEntry]) -> dict[str, str]:
    """Text of small blobs in one `git cat-file --batch` call; binary and oversized blobs are skipped."""
    wanted = [e for e in entries if e.size <= MAX_BLOB]
    if not wanted:
        return {}
    raw = _git_raw(["cat-file", "--batch"], cwd=repo, stdin="".join(f"{e.sha}\n" for e in wanted).encode())
    out: dict[str, str] = {}
    pos = 0
    for e in wanted:
        nl = raw.index(b"\n", pos)
        header = raw[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            continue  # "<sha> missing"
        size = int(header[2])
        data = raw[pos : pos + size]
        pos += size + 1
        if b"\x00" not in data[:2000]:
            out[e.path] = data.decode("utf-8", errors="replace")
    return out


def commit_log(repo: Path) -> list[dict]:
    try:
        out = _git(["log", "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s", "HEAD"], cwd=repo)
    except GitHubError:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            commits.append(
                {"sha": parts[0], "author": parts[1], "email": parts[2], "date": parts[3], "subject": parts[4]}
            )
    return commits
