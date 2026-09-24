# Changelog

## 1.0.0 (2026-09-24)

First complete release: all 12 milestones of [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Milestone 12: testing and deployment
- **End-to-end journey test** (`tests/e2e/`). It runs one user's whole path through the HTTP API: CV upload → fact review → scan → explained match → application prepared, written, approved and tracked → interview practice → skill gaps and learning plan → evening pipeline → daily report and notification → health, metrics and audit trail → sign out. Only the job boards are faked.
- **Coverage**: 87% of the backend, with an 85% floor enforced in CI.
- **Dashboard Docker image** (`frontend/Dockerfile`): the Next.js standalone server runs non-root on a read-only filesystem. CI builds and Trivy-scans both images.
- **Compose**: API, scheduler, dashboard and PostgreSQL, all bound to 127.0.0.1, with `cap_drop: ALL` and read-only containers. Redis is removed (it was unused since the scheduler replaced Celery).
- **Production override** (`deploy/`): Caddy with automatic HTTPS is the only public service. The API runs in production mode with secure cookies, and daily verified `pg_dump` backups keep 14 days.
- **`.dockerignore`**: build contexts can never include `storage/` (your CV and database), `.env` or keys.
- **`scripts/smoke.py`**: a read-only check of a deployment covering pages, the API behind the proxy, headers, `/metrics` not being public, and HSTS and the HTTPS redirect.
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**: local Windows use, a server with Docker, upgrades, rollback, backups and restore, and configuration reference.

### Earlier milestones
| Version | Milestone |
|---|---|
| 0.11 | Observability + security hardening: redacted JSON logs, system health, Prometheus/Grafana, daily backups, sessions and 2FA UI, rate limits |
| 0.10 | Scheduler + notifications: exactly-once pipelines with catch-up, dashboard/email/Telegram alerts, daily report |
| 0.9 | Skill gaps, learning guides and concept maps (levels change only with evidence) |
| 0.8 | Interview coach: 72-question bank, CV-specific questions, daily pack, mock interviews, spaced repetition |
| 0.7 | Application engine: tailored CV, cover letter and answers from verified facts; validator; policy; assisted apply |
| 0.6 | Web dashboard (Next.js) |
| 0.5 | Explainable Estimated Resume-to-Job Fit Score with knockouts |
| 0.4 | Job search: 9 read-only sources, extraction, Pakistan eligibility with evidence, dedup |
| 0.3 | GitHub analyser: evidence from code and config, never from repo names |
| 0.2 | Resume analyser: facts with sources, conflicts and review |
| 0.1 | Backend, schema, auth, audit log, encrypted secrets |
