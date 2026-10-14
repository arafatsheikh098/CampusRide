# DEPLOY.md — Operating CampusRide in production

This document covers everything needed to run CampusRide on a single
host (typical pilot) or as a multi-host service. Read it end-to-end
before the first deploy.

> **Scope reminder.** CampusRide is intentionally small. The
> architecture is one web process and one or more worker processes
> behind a Postgres database. There is no Redis, no message queue, no
> S3, no CDN. Anything that would pull in those services is **out of
> scope** (see `SCOPE.md`).

---

## 1. Architecture

```
                ┌──────────┐
   browser ───▶ │  web     │ ──▶ Postgres
                │ (uvicorn)│      ▲
                └──────────┘      │
                                  │
                ┌──────────┐      │
                │  worker  │ ─────┘
                │ (loop)   │
                └──────────┘
```

- **`web`** — the FastAPI app served by uvicorn. Optionally runs the
  background worker in-process (`RUN_WORKER_IN_PROCESS=true`) — only
  for single-host pilots.
- **`worker`** — the same container running `python -m app.worker`.
  On Postgres a session-level advisory lock guarantees only one
  worker dispatches at a time, so a horizontally-scaled worker
  service is safe.
- **`db`** — Postgres 16. Alembic owns the schema; the app does not
  call `metadata.create_all` in production.

---

## 2. Environment variables

The whole configuration is read by pydantic-settings from environment
variables. The defaults in `app/config.py` are safe for local
development; for production every value below must be set.

| Variable | Required | Example | Notes |
|---|---|---|---|
| `APP_ENV` | **yes** | `production` | Refuses to start if `SECRET_KEY` is the placeholder or < 32 chars. |
| `SECRET_KEY` | **yes** | `openssl rand -base64 48` | Used to sign session cookies. Rotate by reissuing all sessions. |
| `DATABASE_URL` | **yes** | `postgresql+psycopg://campusride:STRONG@db:5432/campusride` | Use the `psycopg` driver. The included `psycopg[binary]` wheel covers most platforms. |
| `DEFAULT_LANG` | no | `en` | One of `SUPPORTED_LANGS`. |
| `SUPPORTED_LANGS` | no | `en,bn` | Comma-separated 2-letter codes. Validated at startup. |
| `CAMPUS_NAME` | no | `North Campus` | Shown in the UI and on trusted-link pages. |
| `CAMPUS_TIMEZONE` | no | `Asia/Dhaka` | Used to display times. Storage is always UTC. |
| `EMERGENCY_NUMBER` | no | `999` | Validated: 3–6 digits. |
| `MEMBER_CAP` | no | `200` | Hard cap on approved members; new signups beyond the cap are refused. |
| `RETENTION_DAYS` | no | `90` | How long trips, bookings, notifications, and resolved reports are kept. |
| `TRIP_HORIZON_DAYS` | no | `14` | How far ahead trips can be posted; capped at 60 by validator. |
| `LAST_MINUTE_WINDOW_MINUTES` | no | `120` | Cancellations inside this window before departure are flagged for moderators. |
| `TIME_MATCH_TOLERANCE_MINUTES` | no | `15` | Search-window overlap tolerance. |
| `COST_PER_SEAT_CAP_PAISA` | no | `50000` | Highest `cost_per_seat_paisa` a trip can declare; capped at 100 000 by validator. |
| `RUN_WORKER_IN_PROCESS` | no | `false` | Set to `true` only on a single-host pilot. |
| `HEARTBEAT_INTERVAL_SECONDS` | no | `30` | How often the worker updates `/health`. |
| `TELEGRAM_BOT_TOKEN` | no | `<bot token>` | When unset, Telegram features are hidden. |
| `TELEGRAM_WEBHOOK_SECRET` | no | `<32+ char secret>` | Must be ≥ 32 chars when set. |
| `WOMEN_ONLY_TRIPS` | no | `false` | Gates the women-only flag on trips. |
| `DEMO_MODE` | no | `false` | Adds the demo banner; never enable in production. |

---

## 3. Single-host pilot (one box, Docker Compose)

This is the recommended starting point. The web and worker run as
two services against a local Postgres volume.

```bash
# 1. Clone and set the environment.
git clone https://github.com/.../CampusRide
cd CampusRide
cp .env.example .env  # if you maintain one; otherwise see below
```

Set at minimum:

```bash
export APP_ENV=production
export SECRET_KEY="$(openssl rand -base64 48)"
export DATABASE_URL="postgresql+psycopg://campusride:STRONG_PASSWORD@db:5432/campusride"
export RUN_WORKER_IN_PROCESS=false   # run worker as a separate service
```

Apply the migrations (only on first deploy):

```bash
docker compose run --rm web python -m app.cli upgrade-db
```

Bootstrap a moderator:

```bash
docker compose run --rm web python -m app.cli create-moderator \
    --mobile 01700000001 \
    --password 'choose-a-strong-password' \
    --full-name "Mod Mira" \
    --department "Staff" \
    --batch "N/A"
```

Start the stack:

```bash
docker compose up --build -d
```

Smoke test:

```bash
scripts/smoke_test.sh http://localhost:8000
```

### A note on `RUN_WORKER_IN_PROCESS`

For a single-host pilot where you want one container per host, you can
collapse the worker into the web container by setting
`RUN_WORKER_IN_PROCESS=true`. The FastAPI lifespan starts the worker
as a background task. **Do not** enable this when running multiple
web replicas — every replica would race for jobs. (The advisory
lock on Postgres is the real safety net, but disabling the lock is
not on the roadmap.)

---

## 4. Multi-host (horizontal web replicas)

Two web containers behind a load balancer, one or more worker
containers. Steps:

1. Run Postgres somewhere reachable by all hosts (managed RDS,
   self-hosted, etc.).
2. Run `python -m app.cli upgrade-db` once from any host.
3. Run `python -m app.cli create-moderator …` once.
4. Run `uvicorn app.main:app --host 0.0.0.0 --port 8000` on each
   web host with the same `DATABASE_URL` and `SECRET_KEY`. **Do
   not** set `RUN_WORKER_IN_PROCESS=true`.
5. Run `python -m app.worker` on each worker host. The advisory
   lock prevents two workers from claiming the same job.

Set up the Telegram webhook by talking to the Bot API once per
deployment:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
     -d "url=https://campusride.example.com/telegram/webhook" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

---

## 5. Reverse proxy

The app expects to be reached over HTTPS in production. Either use
the platform's managed TLS termination or front it with nginx /
Caddy. Required headers from the proxy:

- `X-Forwarded-Proto: https` — so the app can mark session cookies
  `Secure`.
- `X-Forwarded-For` — for any future rate limiting by IP.

The app already sets every security header it needs; the proxy
should not strip them.

---

## 6. Operations

### Health

`GET /health` returns 200 only when the database is reachable **and**
the worker heartbeat is fresh (default ≤ 120 s). Use it as the
load-balancer health check.

### Migrations

```bash
# Apply
docker compose run --rm web python -m app.cli upgrade-db

# Roll back one revision (rare)
docker compose run --rm web python -m app.cli downgrade-db
```

CI runs `upgrade → downgrade → upgrade` on every push. The
`alembic_version` row in Postgres always points at `head`.

### Retention purge

```bash
# Drop cancelled trip instances, terminal-state bookings, old
# notifications and resolved reports older than RETENTION_DAYS.
docker compose run --rm web python -m app.cli purge
```

Add this to a daily cron on the operator host:

```cron
17 3 * * *  cd /opt/campusride && /usr/local/bin/docker compose run --rm web python -m app.cli purge >> /var/log/campusride/purge.log 2>&1
```

### Backup

Standard `pg_dump` against the Postgres service. The audit log
(`audit_logs` table) is part of the data set; back it up too.

### Logs

The worker logs to `campusride.worker` (Python logging). The web
process logs through uvicorn. Capture stdout to your platform's log
collector; there is no PII in the audit log (mobile numbers are no
longer written there — see `git log` for the hardening pass).

### Restart

`docker compose restart web worker` is safe at any time. In-flight
requests get a 502 from the load balancer; pending jobs stay in the
queue because `mark_done` only runs after the handler returns.

---

## 7. Hardening checklist

- [ ] `SECRET_KEY` is a 48-byte random string, stored only in
      the secrets manager, not in the repository.
- [ ] `APP_ENV=production` (the app refuses to start with the
      placeholder `SECRET_KEY` or any key under 32 chars when
      `APP_ENV=production`).
- [ ] `DATABASE_URL` uses a strong password and TLS (`?sslmode=require`
      if your Postgres is reachable over the public internet).
- [ ] `RUN_WORKER_IN_PROCESS` is `false` when more than one web
      replica runs.
- [ ] `DEMO_MODE=false`.
- [ ] `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` (if used)
      are set and the webhook is registered with `setWebhook`.
- [ ] HTTPS is terminated upstream and the proxy sets
      `X-Forwarded-Proto: https`.
- [ ] `/health` returns 200 from the public URL.
- [ ] The retention cron is installed and the latest run is
      visible in `/var/log/campusride/purge.log`.
- [ ] A moderator account exists; the operator can sign in.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `/health` returns 503 with `db.ok=false` | `DATABASE_URL` is wrong, or Postgres is down, or the migrations were not run. |
| `/health` returns 503 with `worker.healthy=false` | The worker process is not running, or the heartbeat is older than 120 s. |
| Sign-in form bounces | The `cr_session` cookie is set with `Secure` but the request is over plain HTTP. Make sure the proxy sets `X-Forwarded-Proto: https`. |
| Telegram `/telegram/webhook` returns 403 | The `X-Telegram-Bot-Api-Secret-Token` header is missing or doesn't match `TELEGRAM_WEBHOOK_SECRET`. |
| `purge` reports `0` for every category | All rows are younger than `RETENTION_DAYS`; this is normal. |
| Signup fails with `password_mismatch` | The signup form requires the same password twice; case-sensitive. |
