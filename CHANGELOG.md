# Changelog

## 1.2.0 (2026-09-24)

### Multiple users
- **Invite-only accounts.** The administrator creates invitation links on the new **Users** page, and people sign up on `/signup` with their own password. Links can be tied to one email address, work once and expire. Only a hash of the token is stored.
- **Roles.** Admin (you); **member**, with their own CV, facts, matches, applications, interview practice, learning, settings and keys; viewer (read only). Job sources, users and invites, system health and backups are **admin-only**.
- **Strict separation.** Every query is scoped to the signed-in person. A test checks that a member sees none of another person's applications, facts, notifications, reports, sessions or learning items, and that direct links to them are refused.
- **One fetch serves everyone.** The morning scan fetches postings once, with the administrator's source keys and quota and the combined target roles of all members. Then each person's matches are scored against their own CV.
- **Onboarding.** New members start from neutral settings. They get a CV **upload card** (drag and drop, on Profile & facts) and a four-step welcome guide on the Dashboard.
- **Deactivating** a member signs them out everywhere immediately.
- Migration `0008`: the `member` role and an `invites` table, tested on SQLite and PostgreSQL.

### AI fix
- Groq retired `llama-3.3-70b-versatile`, so the default is now `openai/gpt-oss-120b`. **If a provider retires a model again, the app picks the best available model automatically and retries.** Test AI reports the switch.
- Settings suggests the models your key can use.
- Error messages include the provider's own explanation.
- Prompts always ask for JSON, which Groq requires.

## 1.1.0 (2026-09-24)

- **Tailor my CV** (new page): paste any job and get a CV and cover letter tailored to it. The job is saved and scored, a package is built from your facts, and it is optionally rewritten by AI.
- **Free AI rewriting**, with the provider chosen in Settings → AI: **Groq**, **Google Gemini** (both free API keys) or **Ollama** (runs on this computer). The AI rewrites the summary, bullets, cover letter and a "why this company" draft. **Every AI line is re-validated**: a skill, tool or number that your cited facts don't support is discarded, your original wording is kept, and the reason is shown. Contact details are never sent to the AI. "Rewrite with AI" and "Rebuild from facts" (undo) are on every application.
- Keys are stored encrypted (`groq_api_key`, `gemini_api_key`), with a **Test AI** button. Rate limits apply, and the AI endpoints are limited to known hosts (Ollama only on localhost).
- Redesigned dashboard: sidebar navigation, indigo/slate theme, Inter, fit-score gauges, a new sign-in page.
- Migration `0007` (AI settings).

## 1.0.1 (2026-09-24)

First release with every CI check green on GitHub (lint, gitleaks, pip-audit, SQLite and PostgreSQL tests,
frontend, compose validation, image builds + Trivy).

- **Fix:** the daily interview pack keeps its planned order. On PostgreSQL it could come back shuffled after a reload, because the order came from the database. Migration `0006` adds `interview_questions.position`.
- **Dashboard image:** npm, npx, corepack and yarn are removed from the runtime stage. They were unused, and they carried 4 HIGH CVEs from the base image.
- **API image:** uses uv 0.11, which can read the current `uv.lock`.
- **CI:** Trivy action `v0.36.0`; `.gitleaks.toml` allows the deliberately fake keys in `tests/`.

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
