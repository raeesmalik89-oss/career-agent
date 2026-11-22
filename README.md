# Career Agent

An agentic job-search, application, skill-gap and interview-prep platform for **DevOps / SRE / AIOps / MLOps / AI-platform** roles in Islamabad and remote.

It never invents experience, never bypasses CAPTCHA/MFA, never automates platforms whose terms forbid it, and labels every score as an **Estimated Resume-to-Job Fit Score**, never a hiring probability.

The design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Deploy it free (open in your browser)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/raeesmalik89-oss/career-agent)

Click the button (or point a Render Blueprint at this repo). It stands up the backend, the
dashboard and a PostgreSQL database on Render's **free** tier and gives you a public URL to open.
You only paste one generated secret. Full walkthrough: **[DEPLOY.md](DEPLOY.md)**.

## Milestone status

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Repository + backend + database | ✅ done |
| 2 | Resume Analyzer | ✅ done |
| 3 | GitHub Analyzer | ✅ done |
| 4 | Job Search Engine | ✅ done |
| 5 | Matching Engine | ✅ done |
| 6 | Dashboard | ✅ done |
| 7 | Application Engine (assisted apply) | ✅ done |
| 8 | Interview Coach | ✅ done |
| 9 | Skill Gap + Concept Maps | ✅ done |
| 10 | Scheduler + Notifications | ✅ done |
| 11 | Observability + Security hardening | ✅ done |
| 12 | Testing + Deployment | ✅ done (v1.0.0) |

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

### What Milestone 4 contains
- **Read-only connectors** (`integrations/sources/`): RemoteOK, Remotive (3 category feeds a day, per its terms), Himalayas, Arbeitnow, We Work Remotely (RSS), and the company boards of Greenhouse, Lever and Ashby (you choose the companies), plus Jooble (needs your free API key; covers Islamabad) and manual paste. LinkedIn/Indeed/Glassdoor/Rozee are never scraped.
- **Safe HTTP client**: https only, host allowlist (SSRF guard, including redirects), 20 MB cap, per-host pacing, and a 90 s limit on the whole response (one slow server can't stall a scan).
- **Deterministic extraction** (`agents/job_agent/extract.py`): role family, seniority, years required, required vs preferred skills (by section headings), remote type, salary (only when the posting states it), visa and clearance. **Pakistan eligibility always comes with the text that justifies it**; if nothing is stated it is `unknown` ("Evidence not found."), never eligible.
- **Deduplication**: the same vacancy on several boards becomes one job with every source linked. Location variants are merged, and if any variant accepts Pakistan the job is eligible. A job only gets a new `content_version` when its own posting changes materially (title, seniority, remote, eligibility, salary or required skills), so unchanged jobs are never shown twice.
- **Daily minimum**: if fewer than `daily_min_jobs_scanned` postings are found, the scan widens its queries and reports any shortfall. Scores are never inflated to compensate.
- 30+ mock jobs (`tests/fixtures/jobs.py`) and a fake HTTP client, so the tests never use the network.

### What Milestone 5 contains
- **Job Matcher Agent** (`agents/match_agent/`) runs at the end of every scan, and on demand with no network access (`match-jobs`, `POST /matches/run`).
- **Estimated Resume-to-Job Fit Score (0-100)**, deterministic and explainable. It is always shown with its confidence and the disclaimer *"Measures overlap between your verified profile and the posting. It is not a probability of being hired."*
- **Seven weighted components** (weights in Settings, default 30/20/15/10/10/10/5):
  - **Skills**: per skill, 1.0 = used in resume experience/projects *and* GitHub; 0.8 = resume use only; 0.7 = GitHub only; 0.5 = listed only or an adjacent skill; 0 = "Evidence not found.". Required skills count 75% and preferred 25%.
  - **Experience**: dated technology experience only, with overlaps counted once. Training programmes are counted but flagged as a risk.
  - **Project/GitHub evidence**: which skills are backed by your repos, plus recent activity and tests/CI.
  - **Education and certifications**: a Level 6 diploma is described as a diploma, never as a degree, and a degree in an unrelated field is reported as such.
  - **Role family and seniority**; **location and remote** (Pakistan eligibility with its quoted evidence); **domain** (e.g. healthcare).
- **Knockouts hide a job and say why**: not open to Pakistan; on-site/hybrid outside your cities; security clearance (a "no clearance required" posting is not a knockout); seniority 2 or more levels above your verified level; experience required more than 2x your verified years. The last two limits are configurable in the Settings policy.
- **Never re-shown**: there is one match per job *version*. Re-scoring after a profile or Settings change updates that match in place and keeps its "seen" state. Only a material change to the posting creates a new, unseen match.
- **Stored per match**: component points and explanations, evidence (fact IDs and GitHub repos), missing and partial skills, risks, knockouts and a recommendation.

### What Milestone 6 contains
- **Web dashboard** (`frontend/`, Next.js 16 + TypeScript + Tailwind). Pages: Dashboard, Matches, All jobs, Job detail, Profile & facts, GitHub, Settings, Activity. Light and dark themes; works at phone width.
- **Matches**: jobs at or above your threshold, all eligible jobs, or everything including hidden ones with the knockout reason. Each shows the score with its confidence and disclaimer, missing and partial skills, risks and a recommendation. You can mark matches seen or dismiss them.
- **Job detail**: every score component with its explanation, a per-skill evidence table (credit, basis, the repos that back it), why it matches or not, and the posting's facts with the quoted Pakistan-eligibility evidence. The posting text is shown as plain text (it is untrusted).
- **Fact review**: verify, reject or restore each fact, verify several ticked facts at once (facts with conflicts or that you rejected are skipped), and resolve conflicts by picking the value that is right. Rejecting a skill or editing experience recomputes your skill levels.
- **Settings** with live validation (weights must add up to 100), then a one-click re-score. **Activity** shows the append-only audit log and every agent run.
- **Security**: the browser only talks to the dashboard's origin. `/api` is proxied to FastAPI, so the httpOnly SameSite=strict session cookies are used and page JavaScript never sees a token. Includes CSP, `X-Frame-Options: DENY`, `no-referrer`, and a redirect after login that only allows same-site paths.
- New API: `GET /api/v1/dashboard`, `POST /api/v1/profile/facts/verify-bulk`.

### What Milestone 7 contains
- **Application Engine** (`agents/application_agent/`): press **Prepare application** on any job to get a tailored resume (DOCX, ATS-safe single column), a cover letter and a set of standard answers. **Nothing is ever sent**: every package waits in your approval queue.
- **Tailoring only selects and reorders your facts.** Skills the job asks for come first; the most relevant bullets and projects are chosen; technologies you have no evidence for are never listed. Anything that needs your own words (why this company, salary) is left as a `[placeholder]` that blocks approval until you write or clear it.
- **Validator (compliance)** checks every line: the cited fact must exist and not be rejected (else **unsupported**); every technology named must be in your evidence; every number must appear in a cited fact or be derived from dated facts ("Evidence not found." otherwise). Pending facts, conflicts and placeholders are marked for review. Unsupported lines block approval.
- **Policy engine** with a stored rule trace (version `2026-09-24.1`): auto-submit needs auto-apply on, a source that allows automation, no unsupported or unreviewed items, no sensitive questions (open-ended, salary, visa, relocation, legal, demographic), non-low confidence, known eligibility and the daily limit. With your settings everything goes to approval.
- **Assisted apply and tracking**: after you approve, open the posting, upload the resume, paste the answers (copy buttons), submit it yourself, then mark it applied; then interview stages, offer, rejected or withdrawn. Every step is an event plus an audit entry.
- **Duplicate guard**: one application per job, plus a same-company, near-identical-title check within 60 days (reposts).
- Automated form submission (browser automation) is not part of this milestone.

### What Milestone 8 contains
- **Question bank** (`data/interview/*.yaml`, 72 questions, validated on load): Linux and networking, Docker and Kubernetes, Terraform and CI/CD, AWS and Azure, observability and SRE, DevSecOps, AIOps/MLOps/AI, system design, troubleshooting scenarios and HR. Each has what it tests, key concepts, a model answer, common mistakes, a follow-up and a simple spoken-English version. A test checks that every model answer passes its own rubric.
- **Questions about you** (`agents/interview_agent/personal.py`): a walk-through for each CV project (only technologies you have evidence for), a "how exactly did you measure that?" question for every number in your CV, and personal HR questions ("tell me about yourself", your career change, training-only experience) with outlines built from your facts. Nothing is invented.
- **Daily pack** of 60 questions in 6 sections (target-job skills, gaps, your projects, troubleshooting, design and SRE, HR), weighted by how often your target jobs ask for each skill. Spaced repetition: questions you scored under 70 in the last 14 days come back; questions you aced rest; never-shown questions come before repeats.
- **Mock interview**: one question at a time. The model answer is hidden until you answer. The score uses the architecture's rubric (accuracy 40, completeness 25, structure/STAR 15, depth 10, communication 10) and shows what you covered, the concepts you missed, mistakes, the model answer, a spoken version and the likely follow-up. For questions about a CV number, an answer that never addresses that number is capped. The scoring is automatic, based on concept coverage and structure, and says so: it cannot judge whether each statement is true. An AI grader can be plugged in later.
- **Progress**: averages by section, a 30-day trend, and the questions to practise again.
- Migration `0003` adds question-bank identity, key points, spoken answers and the rubric breakdown.

### What Milestone 9 contains
- **Skill-gap analysis** (`agents/skill_agent/gaps.py`) over the jobs in your target roles that are open to you, for 1, 7 or 30 days: how often each skill is asked for (required counts 1, preferred 0.5), the 7-day trend, your status (have / partial / missing, with the reason) and a priority = 40% frequency + 25% role importance + 20% gap severity + 15% interview importance. Daily reports are saved in `skill_gaps`.
- **Learning guides** (`data/learning/*.yaml`, validated) for your top gaps: SRE, GCP, platform engineering, GitOps, LLMs, vector databases, agentic AI, Datadog, Java and PowerShell. Each has why it matters to you, an explanation, a cheat sheet, commands (checked against an allowlist of real tools), a hands-on lab, troubleshooting, official https resources, and a mini-project that states which GitHub evidence it produces.
- **Concept maps** (concept → components → interactions → production use → DevOps use → interview traps → commands → troubleshooting → related), validated for depth ≤ 5 and ≤ 80 nodes, rendered as an interactive tree, a Mermaid mind map and Markdown, and versioned in `concept_maps`.
- **Learning plan**: six checklist items per skill. **Completing items never changes a skill level**; only evidence does (the CV, or code the GitHub analyser finds).
- **New GitHub detectors**, so learning turns into evidence: Java (sources, pom.xml, Gradle), PowerShell scripts, Datadog (ddtrace, agent config), SLO specs (Sloth, OpenSLO, SLO recording rules, which also imply SRE), vector stores (Chroma, FAISS, Pinecone, Qdrant, Weaviate, pgvector), RAG (a vector store plus retrieval code) and agents (LangGraph StateGraph, tool definitions, CrewAI, AutoGen, MCP).

### What Milestone 10 contains
- **Scheduler** (`scheduler/`, run as `python -m scheduler`; `start-career-agent.cmd` opens it in a minimised window). A small cron engine (5 fields, time-zone aware, default Asia/Karachi) replaces Celery Beat for this single-user install. There is no Redis or broker; the database is the source of truth.
- **Pipelines** (times editable under Settings → Automation):
  - `morning_scan` 07:00: scan, dedupe, score, alert on new matches at or above your threshold (capped at 10 plus a summary), and **prepare** packages for up to 5 of them. It never submits.
  - `delta_scan`: optional midday scan, off by default to save Jooble quota.
  - `afternoon_analysis` 14:00: 1/7/30-day skill gaps, with an alert when a skill enters your top 5.
  - `evening_prep` 20:00: tomorrow's interview pack and today's Daily Career Report.
  - `weekly_sync` Sunday 10:00: GitHub re-sync and re-score.
  - `housekeeping` hourly: retries failed email/Telegram deliveries and closes interrupted runs.
- **Exactly once**: each slot (user, pipeline, fire time) is a unique `pipeline_runs` row, so restarts or a second scheduler never double-run it. A slot missed while the computer was off is **caught up** when the scheduler next starts, if at most `catch_up_hours` (default 12) late, and it works for its own date (yesterday's report is yesterday's). Only one pipeline runs at a time. Steps commit separately; a failing step is recorded, the others still run, and you get an alert.
- **Notifications**: always shown under the bell icon, and optionally copied by **email** (SMTP, TLS required) or **Telegram**.
  - A dedup key means one alert per job, however often scans repeat, and alerts skip matches you have already opened.
  - Email and Telegram only get alerts at or above a chosen severity, and wait out quiet hours (urgent ones excepted).
  - Failed deliveries are retried up to 5 times.
  - The SMTP password and bot token are stored encrypted; errors are scrubbed of them.
- **Daily Career Report** (`agents/report_agent/daily.py`): counts only, with nothing estimated. It covers postings fetched, new jobs, matches, what hid jobs, applications waiting for you, interview practice, learning progress, top gaps, pipeline results and Jooble quota. It can also be emailed as a digest.
- **Dashboard**: an **Automation** page (scheduler status, next and last run, run now, step details), **Notifications** (bell with unread count), **Daily reports**, and new Settings cards for Automation and Notifications (with Send test).
- SQLite now uses WAL and a busy timeout, because the API and the scheduler share the file. Migration `0005` adds `pipeline_runs`, `scheduler_state`, notification dedup keys and notification settings.

### What Milestone 11 contains
- **Structured logs** (`backend/app/core/logging.py`): JSON lines with the request ID (`LOG_FORMAT=text` for a terminal; the Windows launcher uses it). Access logs record the route template and duration, never the raw URL.
- **Redaction everywhere** (`backend/app/core/redact.py`): log lines, tracebacks, stored agent errors and pipeline errors are scrubbed. This covers bearer tokens, JWTs, GitHub, Telegram and API keys, `password=` pairs, URL credentials and Jooble keys.
- **System health** (`GET /api/v1/system/health`, shown at the top of the Automation page). It checks:
  - database latency, and whether migrations are pending;
  - the scheduler heartbeat and the last run of each pipeline;
  - time since the last job fetch, and failed deliveries;
  - Jooble quota, backup age and free disk;
  - configuration.
- **Prometheus `/metrics`**:
  - HTTP traffic and latency;
  - auth events (logins, failures, token reuse) and rate-limit refusals;
  - health gauges computed from the database, so they also cover the scheduler process.

  Needs `METRICS_TOKEN` when scraped from another host.
- **Prometheus + Grafana** (`infra/observability/`, `docker compose --profile observability up -d`): 11 alert rules (scheduler down, pipeline failing, stale scan or backup, failing deliveries, low quota, 5xx rate, login-failure spike, refresh-token reuse) and a provisioned dashboard.
- **Daily verified backups** of the SQLite database (housekeeping; `storage/backups/`, 14 kept). Also available with **Back up now** and `app.cli backup`.
- **Account security** (Settings): change password (signs out other devices), list and sign out devices, and turn 2FA on or off in the dashboard.
- **Hardening**:
  - stricter response headers (CSP, COOP/CORP, Permissions-Policy, HSTS with secure cookies);
  - a 25 MB request limit, and safe request IDs;
  - per-user rate limits on expensive or sensitive actions;
  - startup configuration checks (production refuses weak settings);
  - `pip-audit` in CI.

  Tests now run in a sandbox and can never touch `storage/`. See [SECURITY.md](SECURITY.md).

### What Milestone 12 contains
- **End-to-end journey test** (`tests/e2e/test_journey.py`). One user goes through the whole product over HTTP:
  CV → fact review → scan → explained match → application (written, approved, marked applied by you) → interview practice → skill gaps and plan → evening pipeline → report and notification → health, metrics and audit trail → sign out.
- **Coverage** is 87%, with an 85% floor in CI (`make cov`). CI also validates both compose files and builds and Trivy-scans both images.
- **Dashboard image** (`frontend/Dockerfile`, Next.js standalone, non-root) and a compose stack of PostgreSQL, API, scheduler and web. Everything is read-only, runs with `cap_drop: ALL` and is bound to 127.0.0.1. Redis is removed, because it was unused.
- **Production on a server** (`deploy/`): Caddy with automatic HTTPS as the only public service, strict API settings, and daily verified `pg_dump` backups.
- **`.dockerignore`** keeps `storage/`, `.env` and keys out of every image build.
- **`scripts/smoke.py`**: a read-only post-deploy check (9 checks locally, 11 over HTTPS).
- **Guides**: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Windows, Docker and a server; upgrades, rollback, restore; every setting) and [CHANGELOG.md](CHANGELOG.md).

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
| POST | `/api/v1/jobs/scan` · `/api/v1/jobs/manual` | owner |
| GET | `/api/v1/jobs` (filters: family, remote, pk, q, since) · `/api/v1/jobs/{id}` · `/api/v1/jobs-stats` | any |
| GET | `/api/v1/matches` (min_score, new_only, include_hidden, include_dismissed) · `/api/v1/jobs/{id}/match` | any |
| POST | `/api/v1/matches/run` · `/api/v1/matches/seen` · `/api/v1/matches/{id}/dismiss` | owner |
| PUT | `/api/v1/secrets` (stored encrypted, never returned) | owner |
| GET | `/api/v1/dashboard` | any |
| GET/POST | `/api/v1/applications` · GET `/applications/{id}` · `/resume.docx` · `/cover-letter.docx` | any / owner |
| PATCH/POST | `/api/v1/applications/{id}/answers/{answer_id}` · `/approve` · `/reject` · `/rebuild` · `/status` | owner |
| POST | `/api/v1/profile/facts/verify-bulk` | owner |
| GET | `/api/v1/interview/packs/{date or today}` · `/interview/sessions` · `/sessions/{id}` · `/interview/stats` | any |
| POST | `/api/v1/interview/packs/today/regenerate` · `/interview/sessions` · `/sessions/{id}/answer` · `/sessions/{id}/end` | owner |
| GET | `/api/v1/skills/gaps?window=1\|7\|30` · `/api/v1/learning` · `/api/v1/learning/skills/{key}` | any |
| POST/PATCH | `/api/v1/learning/plan` · `/api/v1/learning/items/{id}` | owner |
| GET | `/api/v1/pipelines` · `/api/v1/pipeline-runs` | any |
| POST | `/api/v1/pipelines/{name}/run` (runs in the background; `?wait=true` to block) | owner |
| GET | `/api/v1/notifications` (unread, before, limit) · `/notifications/unread-count` | any |
| POST | `/api/v1/notifications/{id}/read` · `/notifications/read-all` · `/notifications/test` · GET `/notifications/channels` | owner |
| GET | `/api/v1/reports/daily` · `/api/v1/reports/daily/{date}` · POST `/api/v1/reports/daily` (build now) | any / owner |
| GET | `/api/v1/system/health` · POST `/api/v1/system/backup` | owner |
| POST | `/api/v1/auth/password` · GET `/auth/sessions` · POST `/auth/sessions/{id}/revoke` · `/auth/sessions/revoke-others` | any |
| POST | `/api/v1/auth/totp/disable` | owner |
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
uv run python -m app.cli sources --enable remoteok remotive himalayas weworkremotely arbeitnow greenhouse ashby     --companies greenhouse=gitlab,canonical,grafanalabs,cloudflare,elastic,mongodb,datadog ashby=supabase,posthog,replit,render
uv run python -m app.cli scan-jobs --email you@example.com           # also scores the jobs
uv run python -m app.cli match-jobs --email you@example.com --out storage/matches.json   # re-score only, no network
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

### Everyday use on Windows (double-click)
- `start-career-agent.cmd` applies any database migrations and starts three windows:
  - the API, on port 8010 so it never clashes with a WSL server on 8000;
  - the scheduler, minimised;
  - the dashboard.

  It then opens http://localhost:3000. Close the three windows to stop.
- While the scheduler runs, scans and reports happen by themselves (Automation page). Leave it open, or start it any time: missed runs from the last 12 hours are caught up.
- `scan-jobs.cmd` still runs a scan by hand (about 4 Jooble requests). So does **Run now** on the Automation page, or `uv run python -m app.cli run-pipeline --email you@example.com morning_scan`.
- Scheduler without the dashboard: `set PYTHONPATH=backend;.` then `.venv\Scripts\python.exe -m scheduler` (add `--once` for a single pass, e.g. from Windows Task Scheduler).

### Dashboard (Windows, Node 24+)
Start the API first (port 8000), then in a second terminal:
```powershell
cd frontend
npm install
npm run dev          # http://localhost:3000  (set BACKEND_URL if the API is not on 127.0.0.1:8000)
npm test             # unit tests;  npx tsc --noEmit  type check;  npx next build  production build
```

### WSL / Linux with Docker (full stack)
```bash
cp .env.example .env
make keys            # paste the two values into .env
docker compose up -d --build     # postgres, api, scheduler, web
docker compose exec api python -m app.cli create-owner --email you@example.com --name "Your Name"
# Dashboard: http://localhost:3000   API docs: http://localhost:8000/docs
make smoke url=http://localhost:3000
make test-pg         # runs the suite against PostgreSQL too
```

### Local dev server against Docker Postgres
```bash
docker compose up -d postgres
make migrate seed
make owner email=you@example.com name="Your Name"
make run             # http://localhost:8000/docs
```

## Production
A Linux server with a domain name: `make prod-up`, which is `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build`. Caddy provides automatic HTTPS, the API runs with production checks, and `pg_dump` backups run daily. Then run `make smoke url=https://your-domain`. Step by step, including upgrades and rollback: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Backups and restore (SQLite)
- Backups are made automatically once a day by housekeeping, or with **Automation → Back up now**, or with `uv run python -m app.cli backup` (`--list` to see them). They go to `storage/backups/career-agent-YYYYMMDD-HHMMSS.db`.
- To restore:
  1. Close the three Career Agent windows.
  2. Copy `storage/dev.db` somewhere safe.
  3. Copy the backup you want over `storage/dev.db`.
  4. Run `start-career-agent.cmd` again (it applies any newer migrations).
- PostgreSQL: `docker compose exec postgres pg_dump -U career career_agent > backup.sql`.

## Observability (optional, Docker)
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > infra/observability/metrics_token   # also put it in .env as METRICS_TOKEN
docker compose --profile observability up -d     # Prometheus http://localhost:9090 · Grafana http://localhost:3001 (admin / GRAFANA_ADMIN_PASSWORD)
```

## Security notes
See [SECURITY.md](SECURITY.md) for the full list.
- `.env`, `*.pem`, `*.key` and `storage/` are git-ignored, and CI runs gitleaks.
- Job-platform passwords are never stored. Third-party tokens are stored encrypted in `secrets`.
- `TEST_DATABASE_URL` must name a database containing `test`, because the suite wipes it.
