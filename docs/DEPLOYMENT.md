# Deployment

There are three ways to run Career Agent. Pick one:

| | Where | Database | For |
|---|---|---|---|
| **A** | Your Windows PC (double-click) | SQLite in `storage/` | Daily personal use. This is the current setup. |
| **B** | Any machine with Docker (e.g. WSL) | PostgreSQL in a volume | Trying the container setup locally |
| **C** | A Linux server with a domain name | PostgreSQL + Caddy (HTTPS) | Reaching it from your phone anywhere |

The agents never submit applications or send messages to employers in any of them.

---

## A. Windows, no Docker (current setup)

First time:
```powershell
uv sync
uv run python -m app.cli gen-keys        # copy both values into .env (start from .env.example)
uv run alembic upgrade head
uv run python -m app.cli seed
uv run python -m app.cli create-owner --email you@example.com --name "Your Name"
```
Every day, double-click **`start-career-agent.cmd`**. It:
1. applies new database migrations (safe to repeat);
2. starts the API (port 8010), the scheduler (minimised) and the dashboard (port 3000);
3. opens http://localhost:3000.

Close the three windows to stop. Missed scheduled runs from the last 12 hours are caught up the next time it starts.

**Updating** after new code: `uv sync`, then in `frontend/` run `npm install`, then start as usual (migrations run by themselves).

**Backups**: daily and automatic, in `storage/backups/` (14 kept). To restore one:
1. Close the three windows.
2. Copy `storage/dev.db` somewhere safe.
3. Copy the backup over `storage/dev.db`.
4. Start again.

**Check it**: `uv run python scripts/smoke.py http://localhost:3000`, or open Automation → System health.

> Command-line tools from WSL work on the same `storage/dev.db`. Don't turn on SQLite WAL mode: it breaks access from WSL on `/mnt/e`.

---

## B. Docker on one machine

```bash
cp .env.example .env               # set JWT_SECRET, MASTER_KEY (gen-keys) and POSTGRES_PASSWORD
docker compose up -d --build       # postgres, api (runs migrations + seed), scheduler, web
docker compose exec api python -m app.cli create-owner --email you@example.com --name "Your Name"
python3 scripts/smoke.py http://localhost:3000
```
Everything is bound to 127.0.0.1: http://localhost:3000 is the dashboard, and http://localhost:8000/docs is the API docs.

To move your existing SQLite data into PostgreSQL, re-import your CV (`app.cli import-profile`) and re-run a scan. Your facts need reviewing again, which is safer than copying a half-migrated database.

**Optional monitoring**:
```bash
python3 -c "import secrets;print(secrets.token_urlsafe(32))" > infra/observability/metrics_token   # also METRICS_TOKEN=... in .env
python3 -c "import secrets;print(secrets.token_urlsafe(24))" > infra/observability/grafana_admin_password
docker compose up -d api && docker compose --profile observability up -d
```
Prometheus runs on http://localhost:9090 (with 11 alert rules), and Grafana on http://localhost:3001 (user `admin`, the password from that file). Grafana includes the "Career Agent" dashboard.

---

## C. A Linux server with HTTPS

Requirements:
- a small VPS (1 vCPU, 2 GB RAM);
- Docker with the Compose plugin (v2.24 or later);
- a domain whose DNS A record points at the server;
- ports 80 and 443 open.

```bash
git clone <your repo> career-agent && cd career-agent
cp .env.example .env
# edit .env:
#   APP_ENV=production, JWT_SECRET / MASTER_KEY from gen-keys, a long random POSTGRES_PASSWORD
#   DOMAIN=careers.example.com, ACME_EMAIL=you@example.com
chmod 600 .env
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
docker compose exec api python -m app.cli create-owner --email you@example.com --name "Your Name"
python3 scripts/smoke.py https://careers.example.com        # all checks must pass
```
What the production override changes:
- **Only Caddy is public** (80/443). It gets and renews the Let's Encrypt certificate and redirects HTTP to HTTPS. PostgreSQL, the API, `/metrics` and the dashboard are only reachable on the private Docker network.
- **The API runs in production mode**: secure cookies, CORS limited to your domain, no `/docs`, JSON logs. It **refuses to start** with a weak `JWT_SECRET`, `COOKIE_SECURE=false` or a wildcard CORS origin.
- **Backups**: `pgbackup` makes a verified `pg_dump` every 24 hours into `./backups/`, keeping 14 days. Copy that folder off the server regularly, because a backup on the same disk is not a backup.
- **After signing in**: turn on **two-factor sign-in** (Settings → Account security).

### Upgrading
```bash
git pull
export APP_VERSION=$(git describe --tags --always)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
python3 scripts/smoke.py https://careers.example.com
```
The API applies migrations on start.

### Rolling back
Images are tagged with `APP_VERSION`:
1. Set it back to the previous tag.
2. Check out that tag.
3. Run `up -d` again.

If the new version ran a migration, restore the database backup taken before the upgrade:
```bash
docker compose exec -T postgres pg_restore -U career -d career_agent --clean --if-exists < backups/career-agent-YYYYMMDD-HHMMSS.dump
```

### Restoring a backup on a new server
Deploy as above, then run the `pg_restore` command with your newest dump, and restart with `docker compose ... restart api scheduler`.

### Keep in mind
- **`MASTER_KEY` decrypts your stored tokens.** Losing it means entering the Jooble/SMTP/Telegram keys again, and leaking it exposes them. Keep a copy offline.
- **Logs are JSON on stdout.** Read them with `docker compose logs -f api scheduler`. Secrets are redacted before they are written.
- **It is built for one person on one server.** Rate limits live in process memory, so don't scale the API to several replicas without adding Redis.

---

## Configuration reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | development | `production` enables the strict startup checks and hides `/docs` |
| `DATABASE_URL` | postgres on localhost | `sqlite:///storage/dev.db` locally; compose sets PostgreSQL |
| `JWT_SECRET` | required | Signs session tokens (32+ characters, from `gen-keys`) |
| `MASTER_KEY`, `MASTER_KEY_VERSION` | required | Envelope encryption of stored tokens |
| `COOKIE_SECURE` | true | Must be true over HTTPS; false only for http://localhost |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Exact origins; never `*` |
| `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS` | 15, 14 | Session lifetimes |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | 5 | Per IP and email |
| `TIMEZONE` | Asia/Karachi | Default; schedules use Settings → Automation |
| `STORAGE_DIR` | storage | Uploaded documents, generated files, SQLite backups |
| `BACKUP_KEEP` | 14 | SQLite backups kept |
| `MAX_REQUEST_MB` | 25 | Larger requests get 413 |
| `METRICS_TOKEN` | unset | Bearer token for `/metrics` from another host |
| `LOG_LEVEL`, `LOG_FORMAT` | INFO, json | `text` for a terminal |
| `POSTGRES_USER/PASSWORD/DB` | career / - / career_agent | Docker PostgreSQL |
| `DOMAIN`, `ACME_EMAIL` | - | Production override (Caddy, Let's Encrypt) |
| `APP_VERSION` | latest | Image tag for upgrades and rollback |

Tokens for Jooble, GitHub, SMTP and Telegram are **not** environment variables. Store them in the dashboard (encrypted in the database, never shown again) or with `app.cli set-secret`.
