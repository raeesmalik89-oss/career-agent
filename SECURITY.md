# Security

Career Agent holds a CV, verified career facts, job-board API keys and optional email/Telegram credentials for one
person. This page describes how it protects them and what is deliberately out of scope.

## What is protected, and how

| Asset | Protection |
|---|---|
| Your password | Argon2id hash only. At least 12 characters, not repetitive, not containing your email name. Changing it needs the current password and signs out every other device. |
| Sessions | 15-minute access JWT and a 14-day rotating refresh token in httpOnly, `SameSite=Strict` cookies. The token is only stored as a SHA-256 hash. Reuse of a rotated refresh token revokes every session of that user. Revoked sessions stop working at once, because every request checks its session. Settings → Account security lists devices and signs them out. |
| Login | 5 attempts a minute per IP and email, a 15-minute lockout after 10 failures, and optional TOTP 2FA (the secret is stored encrypted; turning it off needs the password and a code). |
| API keys and tokens (Jooble, GitHub, SMTP, Telegram) | AES-256-GCM envelope encryption with the key name as associated data. Write-only through the API, never returned, and never logged. |
| Logs and stored errors | Every log line, agent error and pipeline error passes a redactor that removes bearer tokens, JWTs, GitHub/Telegram/API keys, `password=`-style pairs, URL credentials and Jooble keys. Access logs record the route template, never the raw URL or query string. Client-supplied request IDs are only accepted if they are `[A-Za-z0-9._-]{1,64}`. |
| Your data (`storage/`) | Git-ignored, and CI runs gitleaks on every push. The SQLite database is backed up daily (a verified online copy, 14 kept). Tests run in a temporary sandbox and never touch it. |
| Audit trail | Append-only `audit_logs`: a trigger rejects UPDATE/DELETE on PostgreSQL. It records logins, failed logins, settings diffs, secret changes, sessions, applications and pipeline runs. |

## Hardening in the API
- **Headers**: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` on JSON responses, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP `same-origin`, a restrictive `Permissions-Policy`, and HSTS when `COOKIE_SECURE=true`. The dashboard sets its own CSP.
- **Size limit**: requests over `MAX_REQUEST_MB` (25) are refused with 413 before any endpoint runs.
- **Rate limits** (per user, per minute):
  - job scan 2, GitHub sync 2;
  - pipeline run 6, re-score 6, report build 6;
  - resume upload 5, password change 5;
  - notification test 3, backup 3;
  - storing a secret 10.

  A refusal returns 429 with `Retry-After`.
- **Outbound requests**: https only, with a host allowlist that also applies to redirects (SSRF guard). There are size and time caps, and nothing fetched is ever executed. GitHub repos are cloned bare and partially, and are never checked out.
- **Startup checks**: in production the API refuses to start if `JWT_SECRET` is weak, `CORS_ORIGINS` contains `*`, or `COOKIE_SECURE` is off. The same checks appear as warnings on the System health panel.
- **`/metrics`** needs `Authorization: Bearer $METRICS_TOKEN` when that is set; otherwise only loopback clients may read it.
- **Dependencies**: CI runs `pip-audit` on the locked Python dependencies, `npm audit` on the dashboard, and Trivy on the Docker image.

## Things the agent will never do
- Submit an application, send a message to an employer, or accept terms on your behalf. At most it *prepares* a package for your review.
- Invent experience. Only verified facts are used, and every generated line cites one.
- Bypass CAPTCHA, MFA or bot checks, or automate sites whose terms forbid it (LinkedIn, Indeed, Glassdoor, Rozee, Mustakbil).

## Out of scope and known limits
- It runs as a single user on a single machine. Rate limits are kept in process memory; several API replicas would need Redis.
- SQLite is for a local install only. On a server, use PostgreSQL with `pg_dump` backups and TLS in front of the API and dashboard.
- Email and Telegram copies of notifications leave your machine. They contain job titles and report counts, never secrets. Leave them off if you don't want that.

## Reporting a problem
This is a personal project. If you find a vulnerability, contact the repository owner privately rather than opening a public issue.
