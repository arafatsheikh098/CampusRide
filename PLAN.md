# PLAN.md — milestones

Each milestone lists the files it creates and the tests it needs. Do not change the architecture or folder structure between milestones.

## M1 — Foundation, jobs table and i18n scaffold
Files (create):
- app/__init__.py
- app/main.py
- app/config.py
- app/db.py
- app/models/__init__.py
- app/models/base.py
- app/models/user.py
- app/models/place.py
- app/models/trip.py
- app/models/booking.py
- app/models/trust.py
- app/models/notification.py
- app/models/job.py
- app/models/heartbeat.py
- app/models/audit.py
- app/phone.py
- app/i18n/__init__.py
- app/i18n/en.json
- app/i18n/bn.json
- app/templates/base.html
- app/static/htmx/htmx.min.js (vendored; not created in M1 if network unavailable — recorded as BLOCKER)
- alembic.ini
- alembic/env.py
- alembic/versions/0001_init.py
- tests/test_health.py
- tests/test_phone.py
- tests/test_i18n.py
- tests/test_migrations.py
- Dockerfile
- docker-compose.yml
- Makefile
- .env.example
- .github/workflows/ci.yml
- pyproject.toml (or requirements.txt — pick smallest option, recorded in DECISIONS)

Tests: /health returns 200 and reports db+heartbeat; phone normalization cases (A3); i18n key parity (A4); Alembic upgrade/downgrade on Postgres and SQLite (A2).

Acceptance: A1 docker compose up --build starts services and /health reflects heartbeat. A2 migrations upgrade/downgrade on Postgres and SQLite. A3 phone normalization table-driven. A4 i18n key parity test. A5 CI green.

## M2 — Accounts, moderator approval and security baseline
Files (create/modify):
- app/auth.py
- app/security.py (CSRF, session)
- app/audit.py
- app/cli.py (create-moderator subcommand)
- app/routes/auth.py
- app/routes/moderation.py (account queue)
- app/templates/auth/*.html
- app/templates/moderation/*.html
- tests/test_auth.py
- tests/test_csrf.py
- tests/test_rate_limit.py
- tests/test_recovery_codes.py
- tests/test_suspension.py
- tests/test_security_baseline.py

Tests: pending/rejected/suspended redirect (G4); wrong password generic error; route discovery (G8); rate limit (A4); recovery codes once; suspension ends session; SECRET_KEY default refused in production.

Acceptance: A1–A7 as in M2 prompt.

## M3 — Places, driver verification and eligibility
Files (create):
- app/routes/places.py
- app/routes/driver_verification.py
- app/templates/places/*.html
- app/templates/driver/*.html
- tests/test_places.py
- tests/test_driver_verification.py
- tests/test_eligibility.py
- tests/test_visibility_scans.py (G3 plates)

Tests: moderator-only mutations; revocation hides future unbooked; plate visibility scan; WOMEN_ONLY_TRIPS=false hides feature.

Acceptance: A1–A5 as in M3 prompt.

## M4 — Trips and recurrence
Files (create):
- app/recurrence.py (pure generator)
- app/routes/trips.py
- app/templates/trips/*.html
- tests/test_recurrence.py
- tests/test_trip_validation.py
- tests/test_trip_posting.py

Tests: table-driven recurrence (DST/Asia-Dhaka); window ≤30 min; seats 1–6; cost cap; no URLs/phones in note; no past departure; series edits touch only future untouched instances; tampered-input posting test (G5); generator imports nothing from web/db; cancellation triggers notification interface.

Acceptance: A1–A6 as in M4 prompt.

## M5 — Matching engine
Files (create):
- app/matching.py (pure)
- app/routes/search.py
- app/templates/search/*.html
- tests/test_matching.py
- tests/test_matching_property.py (hypothesis)

Tests: table-driven cases; ranking worked example; property no violation; module has no web/db imports; results show match reason.

Acceptance: A1–A5 as in M5 prompt.

## M6 — Seat booking
Files (create):
- app/routes/bookings.py
- app/templates/bookings/*.html
- tests/test_booking.py
- tests/test_booking_concurrency.py (Postgres only)
- tests/test_booking_limits.py
- tests/test_audit.py

Tests: 20 concurrent on Postgres → 2 accepted (G2); idempotent accept/decline; daily and pending limits; self-booking and block forbidden; last-minute flag boundary; cancel frees seat once; one audit row per state change.

Acceptance: A1–A7 as in M6 prompt.

## M7 — Contact reveal, trusted-contact link and trust and safety
Files (create):
- app/reveal.py
- app/trusted_contact.py
- app/routes/reveal.py
- app/routes/trusted_contact.py (no auth)
- app/routes/blocks.py
- app/routes/reports.py
- app/routes/moderation.py (extend queues)
- app/templates/blocks/*.html
- app/templates/reports/*.html
- app/templates/trusted_contact.html
- tests/test_reveal_scans.py
- tests/test_trusted_contact.py
- tests/test_blocks.py
- tests/test_moderator_queues.py
- tests/test_emergency_notice.py

Tests: G3 reveal scans; trusted-contact page route/time/driver/vehicle only and 404 on bad/expired; tokens hashed; block visibility; "there was a problem" in mod queue; emergency notice from settings; moderator actions audited.

Acceptance: A1–A7 as in M7 prompt.

## M8 — Notifications, reminders and worker
Files (create):
- app/notifications.py
- app/jobs.py
- app/worker.py
- app/routes/notifications.py
- app/routes/telegram.py
- app/templates/notifications/*.html
- tests/test_worker.py
- tests/test_job_queue.py
- tests/test_telegram.py
- tests/test_health_heartbeat.py

Tests: single worker (advisory lock); visibility timeout retry; dedupe; reminders for accepted only and removed on cancel; no TELEGRAM_BOT_TOKEN hides UI; webhook 403 without secret; idempotent webhook; notification text redacted; /health unhealthy at 2 min.

Acceptance: A1–A8 as in M8 prompt.

## M9 — Privacy operations, seed, Bangla UI and end-to-end tests
Files (create):
- app/templates/404.html
- app/templates/500.html
- app/templates/policy/*.html
- app/cli.py (extend purge + delete-my-data)
- app/seed.py
- tests/test_purge.py
- tests/test_delete_my_data.py
- tests/test_headers.py
- tests/test_playwright_e2e.py
- tests/test_seed_idempotent.py
- tests/test_member_cap.py

Tests: purge boundary; delete-my-data row counts; CSP header + zero console errors; no horizontal scroll at 375px; full e2e flow; seed idempotent; cap blocks new approval.

Acceptance: A1–A7 as in M9 prompt.

## Final phases
- H: hardening pass
- F: fresh-clone test
- D: deployment prep (DEPLOY.md, MODERATOR_GUIDE.md, PILOT.md, scripts/smoke_test.sh)
- R: README
- X: final scope audit (FINAL_REPORT.md)
