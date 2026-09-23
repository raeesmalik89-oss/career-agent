# Career Agent

An agentic job-search, application, skill-gap and interview-prep platform for **DevOps / SRE / AIOps / MLOps / AI-platform** roles in Islamabad and remote.

It never invents experience, never bypasses CAPTCHA/MFA, never automates platforms whose terms forbid it, and labels every score as an **Estimated Resume-to-Job Fit Score**, never a hiring probability.

The design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Milestone status

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Repository + backend + database | ✅ done |
| 2 | Resume Analyzer | ✅ done |
| 3 | GitHub Analyzer | ✅ done |
| 4 | Job Search Engine | next |
| 5 | Matching Engine | |
| 6 | Dashboard | |
| 7 | Application Engine | |
| 8 | Interview Coach | |
| 9 | Skill Gap + Concept Maps | |
| 10 | Scheduler + Notifications | |
| 11 | Observability + Security hardening | |
| 12 | Testing + Deployment | |

### What Milestone 1 contains
- **FastAPI backend** (`backend/app`): health/readiness, Prometheus `/metrics`, request IDs, security headers.
- **PostgreSQL schema for the whole platform** (32 tables) with an Alembic migration. It includes pgvector columns + HNSW indexes and an append-only trigger on `audit_logs`.
- **Auth**: Argon2id passwords, 15-min JWT in httpOnly/SameSite=strict cookies (or Bearer), rotating refresh tokens with reuse detection, optional TOTP 2FA (secret stored encrypted), login rate limit and lockout.
- **RBAC**: `owner`, `viewer`, `system`.
- **Envelope encryption** (AES-256-GCM) for stored tokens.
- **Versioned settings** (preferences, scoring weights, policy, schedules), pre-filled from your CV. Every change is audited with a before/after diff.
- **Job-source registry** (15 sources) with ToS notes. Auto-apply is off everywhere and is **blocked** for LinkedIn/Indeed/Glassdoor/Rozee/Mustakbil.
- **Agent base class**: every agent run is stored in `agent_runs` with `agent_name, run_id, input_summary, actions, output, confidence, errors, timestamp`.
- Tests, Dockerfile, docker-compose, Makefile, and GitHub Actions CI (lint, gitleaks, SQLite + PostgreSQL tests, image build + Trivy).

### What Milestone 2 contains
- **Resume Analyzer Agent** (`agents/resume_agent/`): PDF (including two-column layouts), DOCX and TXT parsing. Every extracted line keeps its page and character offsets.
- **Deterministic extraction** of personal details, experience (title, organisation, dates, training flag, sector), projects, education, certifications, licences, languages, availability and measurable achievements. There is no LLM in this path, so nothing can be invented.
- **Skill taxonomy** (`data/taxonomy/skills.yaml`, 169 skills) with aliases, `implies`, `adjacent` and `outdated`. Ambiguous names such as "Go" are only matched inside a skills list.
- **Cross-version merging**: the same job, degree or project from several CV versions becomes one fact that lists every source. Disagreements (e.g. *Trainee* vs *Intern*) are recorded as **conflicts** for you to resolve, never resolved silently.
- **Fact review**: every fact starts as `pending`; you verify, edit or reject it. Applications may only use verified facts for auto-submit (Milestone 7).
- **Resume Intelligence report**: skills by category with evidence level, experience months per sector (overlaps counted once, training kept separate), missing evidence, duplicate and outdated skills, weak sections, single-source metrics to double-check, and recommendations.
- Skill levels from a resume are capped at `working` (used in experience/projects) or `exposure` (only listed). `strong` requires GitHub evidence (Milestone 3) or your confirmation.

### What Milestone 3 contains
- **GitHub Analyzer Agent** (`agents/github_agent/`): lists public repos through the GitHub API (no token needed), then makes a **bare, partial, read-only clone** (`--filter=blob:limit=1m`). Nothing is checked out or executed, and large model files are never downloaded.
- **File-level detectors** for Dockerfiles, Compose, Kubernetes manifests, Helm/Kustomize, Terraform resources and providers, Ansible, GitHub Actions/GitLab CI/Jenkins, Python imports and API routes, notebooks, dependencies, Prometheus/Grafana/OPA/Keycloak configs and tests. **A repository's name is never evidence.**
- **Evidence strength**: `high` = real code/config/CI; `medium` = declared only (e.g. requirements.txt); `low` = README mention only, which never creates a skill.
- **Authorship**: commits are classified as yours, a server default identity (e.g. `Ubuntu`) or other people. Evidence from repos mostly written by others is downgraded.
- **Project verification**: each resume project is linked to its repo (explicit URL, `github_repo` on the fact, or a distinctive name match). Its claimed technologies are split into *verified*, *README only*, *not found* and *not checkable*.
- **Combined skill levels** (`agents/skill_levels.py`): `strong` needs high evidence in 2 or more of your own repos (plus resume use) or in 3 or more repos; `working` needs 1 repo or resume use; `exposure` means listed only.
- **GitHub Intelligence report**: evidence map, repository scores, resume-vs-GitHub (confirmed / resume-only / GitHub-only) and recommendations.

## API (so far)

| Method | Path | Role |
|---|---|---|
| POST | `/api/v1/auth/login` · `/refresh` · `/logout` | – |
| GET | `/api/v1/auth/me` | any |
| POST | `/api/v1/auth/totp/setup` · `/totp/verify` | owner |
| GET/PUT | `/api/v1/settings` · GET `/settings/history` | any / owner |
| GET/PATCH | `/api/v1/sources` · `/sources/{key}` | any / owner |
| POST | `/api/v1/resume/upload` (multipart, 1-20 files) | owner |
| GET | `/api/v1/resume/versions` · `/api/v1/resume/intelligence` | any |
| GET/POST | `/api/v1/profile/facts` | any / owner |
| PATCH | `/api/v1/profile/facts/{id}` (edit, reject, resolve conflicts) | owner |
| POST | `/api/v1/profile/facts/{id}/verify` | owner |
| POST | `/api/v1/github/sync` | owner |
| GET | `/api/v1/github/repos` · `/api/v1/github/intelligence` | any |
| GET | `/api/v1/audit-logs` · `/api/v1/agent-runs` | owner |
| GET | `/healthz` · `/readyz` · `/metrics` · `/docs` (dev only) | – |

## Run it

### Windows (no Docker): tests only
```powershell
uv sync
uv run pytest
```

### Windows (no Docker): local dev database + your documents
```powershell
uv run python -m app.cli gen-keys          # put both values in .env, plus DATABASE_URL=sqlite:///storage/dev.db
uv run alembic upgrade head
uv run python -m app.cli seed
uv run python -m app.cli create-owner --email you@example.com --name "Your Name"
uv run python -m app.cli import-profile --email you@example.com main_cv.pdf other_cv.docx certificate.pdf
uv run python -m app.cli report --email you@example.com --out storage/resume_report.json
uv run python -m app.cli github-sync --email you@example.com --username your-github --out storage/github_report.json
```
The first file you import is treated as your primary resume. `storage/` (database, copies of your documents, reports) is git-ignored.

### WSL (Ubuntu) without Docker
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
cd "/mnt/e/Users/Acer/Desktop/MY WORK/career-agent"
export UV_PROJECT_ENVIRONMENT=.venv-linux   # keep WSL's environment separate from the Windows .venv
uv sync && uv run pytest
PYTHONPATH=backend:. uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### WSL / Linux with Docker (full stack)
```bash
cp .env.example .env
make keys            # paste the two values into .env
docker compose up -d --build
docker compose exec api python -m app.cli create-owner --email you@example.com --name "Your Name"
# API: http://localhost:8000/docs
make test-pg         # runs the suite against PostgreSQL too
```

### Local dev server against Docker Postgres
```bash
docker compose up -d postgres redis
make migrate seed
make owner email=you@example.com name="Your Name"
make run             # http://localhost:8000/docs
```

## Production (outline; finished in Milestone 12)
One VM (Terraform), `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`, Caddy for TLS, `COOKIE_SECURE=true`, nightly `pg_dump` to object storage. Secrets live in `.env` on the host, never in Git.

## Security notes
- `.env`, `*.pem`, `*.key` and `storage/` are git-ignored, and CI runs gitleaks.
- Job-platform passwords are never stored. Third-party tokens are stored encrypted in `secrets`.
- `TEST_DATABASE_URL` must name a database containing `test`, because the suite wipes it.
