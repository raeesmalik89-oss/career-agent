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
| 4 | Job Search Engine | ✅ done |
| 5 | Matching Engine | ✅ done |
| 6 | Dashboard | ✅ done |
| 7 | Application Engine (assisted apply) | ✅ done |
| 8 | Interview Coach | ✅ done |
| 9 | Skill Gap + Concept Maps | next |
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
- `start-career-agent.cmd` starts the API (port 8010, so it never clashes with a WSL server on 8000) and the dashboard, then opens http://localhost:3000. Close its two windows to stop.
- `scan-jobs.cmd` runs a scan and re-scores (about 4 Jooble requests), then you look at **Matches**.

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
