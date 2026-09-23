# Career Agent

An agentic job-search, application, skill-gap and interview-prep platform for **DevOps / SRE / AIOps / MLOps / AI-platform** roles in Islamabad and remote.

It never invents experience, never bypasses CAPTCHA/MFA, never automates platforms whose terms forbid it, and labels every score as an **Estimated Resume-to-Job Fit Score**, never a hiring probability.

The design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Milestone status

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Repository + backend + database | ✅ done |
| 2 | Resume Analyzer | next |
| 3 | GitHub Analyzer | |
| 4 | Job Search Engine | |
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

## API (so far)

| Method | Path | Role |
|---|---|---|
| POST | `/api/v1/auth/login` · `/refresh` · `/logout` | – |
| GET | `/api/v1/auth/me` | any |
| POST | `/api/v1/auth/totp/setup` · `/totp/verify` | owner |
| GET/PUT | `/api/v1/settings` · GET `/settings/history` | any / owner |
| GET/PATCH | `/api/v1/sources` · `/sources/{key}` | any / owner |
| GET | `/api/v1/audit-logs` · `/api/v1/agent-runs` | owner |
| GET | `/healthz` · `/readyz` · `/metrics` · `/docs` (dev only) | – |

## Run it

### Windows (no Docker): tests only
```powershell
uv sync
uv run pytest
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
