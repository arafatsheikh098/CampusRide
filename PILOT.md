# PILOT.md — Running the first campus pilot

> **Audience.** The operator who is putting CampusRide in front of
> real students for the first time. This is the runbook; the
> technical reference is `DEPLOY.md`, the role guide is
> `MODERATOR_GUIDE.md`.

CampusRide is intentionally small. The pilot runs on **one host**
with **one Postgres volume** and **one or two moderators**. Do not
add Redis, S3, a CDN, or a message queue — none are in scope
(see `SCOPE.md`).

---

## 1. Before the pilot (operator prep)

You need to be ready on day one. The first failure mode of a
small tool is "no-one could sign in" because the deploy was wrong.

### Hardware

- One Linux box (2 vCPU, 2 GB RAM is plenty for a 200-member
  pilot). Docker and Docker Compose installed.
- A reachable Postgres 16 — either the bundled one in
  `docker-compose.yml` or a managed instance (RDS, DigitalOcean,
  etc.). The app uses the `psycopg` driver.
- An HTTPS endpoint in front of the box (Caddy, nginx, or the
  platform's managed TLS).

### Domain and secrets

- A short, friendly domain (e.g. `ride.campus.edu`). Put it behind
  HTTPS — see `DEPLOY.md` §5.
- A real `SECRET_KEY`: `openssl rand -base64 48`. Put it in your
  secrets manager, not in the repo.
- A strong `DATABASE_URL` password.

### Configuration

Set these in `.env` (or your secrets manager):

```bash
APP_ENV=production
SECRET_KEY=...                       # 48 random bytes, base64
DATABASE_URL=postgresql+psycopg://campusride:STRONG@db:5432/campusride
CAMPUS_NAME="North Campus"
CAMPUS_TIMEZONE=Asia/Dhaka
EMERGENCY_NUMBER=999
MEMBER_CAP=200
RETENTION_DAYS=90
RUN_WORKER_IN_PROCESS=false          # use a separate worker service
TELEGRAM_BOT_TOKEN=...               # optional; skip if you don't need Telegram
TELEGRAM_WEBHOOK_SECRET=...          # ≥ 32 chars, only if Telegram is used
WOMEN_ONLY_TRIPS=false               # flip to true when ready
DEMO_MODE=false
```

### First deploy

```bash
git clone https://github.com/.../CampusRide
cd CampusRide
docker compose up --build -d
docker compose run --rm web python -m app.cli upgrade-db
docker compose run --rm web python -m app.cli create-moderator \
    --mobile 01700000001 \
    --password 'choose-a-strong-password' \
    --full-name "Mod Mira" \
    --department "Staff" \
    --batch "N/A"
scripts/smoke_test.sh https://ride.campus.edu
```

`/health` must return `{"ok": true, ...}`. The home page must
return 200. The CSP header must be present. If any of those fail,
do not start the pilot — fix it first.

### Pre-flight checklist

- [ ] `/health` returns 200 with `ok: true` from the public URL.
- [ ] The home page loads over HTTPS and the certificate is valid.
- [ ] You can sign in as the moderator you just created.
- [ ] You can reach `/moderation` and the queue is empty.
- [ ] The smoke test exits 0.
- [ ] You have a backup of the Postgres volume (`pg_dump` is fine).

---

## 2. The first moderator

The first moderator should be a **staff member** you trust with
account approval and driver verification. They are the gate. The
pilot succeeds or fails on their judgement.

Choose someone who:

- Knows most of the campus community by face.
- Can reply to safety reports within a day.
- Is comfortable saying "no" to a friend who wants a ride they
  shouldn't be offering.

Give them a copy of `MODERATOR_GUIDE.md`. Walk them through:

1. The queue at `/moderation`.
2. How to verify a driver (the vehicle description is shown
   publicly; the plate is not).
3. How to suspend a member (immediate, even mid-session).
4. How to handle a safety report (read, decide, resolve; do not
   investigate beyond what the platform shows).

Consider appointing a second moderator early. One moderator going
on leave should not freeze the queue.

---

## 3. The first week

### Day 1 (operator + moderator)

- Operator announces the platform in one channel (campus
  newsletter, a department mailing list, a single WhatsApp group).
  Keep it to one channel — you do not want a "where do I sign up?"
  signal from many sources.
- Moderator is online and approves accounts as they come in.
  Approval is one click.
- Operator watches the worker log and the
  `/var/log/campusride/purge.log` (or whatever your platform
  ships logs to).

### Days 2–3 (signups)

- Expect a flood of signups on day 1, then a trickle.
- Approve or reject every account by the end of the day. Do not
  let pending accounts pile up.
- If the queue overflows past `MEMBER_CAP`, decide whether to
  raise the cap (operator action) or keep it where it is.

### Days 4–7 (first trips)

- The first trips will be intra-campus, short, and tentative.
- The trusted-contact link is the headline feature — encourage
  riders to share it with a family member. It's the part of
  CampusRide the campus most needs.
- Watch for:
  - **Spam accounts** — same name with a digit suffix, or
    accounts with no department. Reject them; the signup form
    already requires a real-looking batch and a real mobile.
  - **Last-minute cancellations** — if the same driver cancels
    twice, talk to them.
  - **Misuse of "Report"** — a report is a safety signal, not a
    dislike button. Treat the first report on a person as
    information, not a verdict.

### End of week 1 (review)

- How many approved members? (Should be growing, not flat.)
- How many verified drivers?
- How many completed trips?
- Any open safety reports? (Target: zero. If non-zero, walk
  through them with the moderator.)
- Any worker errors in the log? (Target: zero. If non-zero,
  the `assert_safe_secret_key` may have failed; check the
  `SECRET_KEY` length.)
- Is the retention purge running? (Check the cron log.)

---

## 4. When to scale

The single-host pilot scales to about **200 members and a few
hundred trips per day** comfortably. Above that, you scale by
**adding web replicas**, not by changing the stack. The
`docker-compose.yml` runs a single web container; on a
single-host pilot that is the right choice.

### Signals you need a second host

- `/health` returns 503 because the worker heartbeat is stale —
  the host is CPU-starved and the worker is delayed.
- Uvicorn is rejecting connections under load.
- You want zero-downtime deploys (run two web replicas behind
  the load balancer; only one carries the worker; the other
  has `RUN_WORKER_IN_PROCESS=false`).

`DEPLOY.md` §4 covers the multi-host case. You will need:

- A managed Postgres reachable from both hosts (`?sslmode=require`
  on the public internet).
- A shared `SECRET_KEY` across both hosts (sessions are signed
  with it; rotating it logs everyone out).
- A way to register the Telegram webhook once per deployment
  if you use Telegram.

You do **not** need: a CDN, an object store, a queue server, a
cache, a search index, a session store, or any other component
that would make the platform more complex. The architecture is
one web process, one worker process, one Postgres. Keep it that
way until the pilot has run for a full semester.

---

## 5. When to abort

Cancel the pilot and reset if any of the following happen:

- `SECRET_KEY` or `DATABASE_URL` leaks (rotate immediately, then
  pause new signups until the cause is known).
- A moderator account is compromised (suspend it, rotate
  `SECRET_KEY` to invalidate every session, then resume).
- A safety report cannot be investigated because the report
  text is insufficient — fix the form before re-opening
  signups.
- The worker stops processing jobs and `/health` is unhealthy
  for more than ten minutes. Pull the load balancer out of
  rotation, fix the worker, then put it back.

In every case, post a short note to the campus channel
explaining what happened and what you changed. Silence is the
worst response.
