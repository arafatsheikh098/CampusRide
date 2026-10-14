# MODERATOR_GUIDE.md — Day-to-day moderation in CampusRide

> **Audience.** A moderator (or a small moderation team) running
> CampusRide on a campus. This document is a how-to; it does not
> re-state the design (see `PROJECT_SPEC.md`, `SCOPE.md`).

A moderator is a normal user account with the `moderator` role and an
approved status. There is no separate admin interface. The
moderation queue is mounted at `/moderation` and only resolves for
approved moderators. Anyone else gets a 404 — the URL is not
advertised.

---

## 1. Roles and reach

| Action | Who can do it | Where |
|---|---|---|
| Approve / reject signups | Approved moderator | `/moderation` → "Pending accounts" |
| Suspend a member | Approved moderator | `/moderation/accounts/{id}` |
| Add or remove pickup places | Approved moderator | `/moderation/places` |
| Verify a driver (plate + description) | Approved moderator | `/moderation/accounts/{id}` |
| Revoke a driver | Approved moderator | `/moderation/accounts/{id}` |
| Grant / revoke women-only eligibility | Approved moderator | `/moderation/accounts/{id}` |
| Resolve a safety report | Approved moderator | `/moderation` → "Open reports" |
| Remove a problematic trip | Approved moderator | `/moderation` → "Last-minute cancels" |
| Resolve a post-trip "had a problem" check | Approved moderator | `/moderation` → "Post-trip problems" |

If your account is **suspended**, you are locked out of every
moderation route immediately, even with a live session cookie. This
is enforced server-side by `require_moderator` (see
`tests/test_hardening.py`).

---

## 2. The queue at `/moderation`

The queue shows four lists, oldest first:

- **Pending accounts** — every signup waiting for review.
- **Open reports** — every un-resolved safety or trip report.
- **Last-minute cancels** — every booking a rider or driver
  cancelled inside `LAST_MINUTE_WINDOW_MINUTES` of departure.
- **Post-trip problems** — every post-trip check where the rider
  answered "Had a problem".

Open one item at a time. Every action writes an audit row
(`audit_logs` table) with your actor id and label.

---

## 3. Approving signups

Open `/moderation`. For each pending account, open the detail page
(`/moderation/accounts/{id}`) and:

1. Confirm the name, department, and batch are plausible for your
   campus. The mobile number is shown only to moderators and is
   never written to the audit log.
2. Click **Approve**. The new user can sign in immediately.
3. If the account should not be on the platform, click **Reject**.
   Rejected accounts can be re-submitted with a corrected mobile;
   we do not ban by IP.

### Member cap

`MEMBER_CAP` (default 200) is a hard ceiling. If approving a new
user would exceed the cap, the route returns `409 member_cap_reached`
and the form does not change. Do not approve past the cap without
raising it in `.env` first.

---

## 4. Verifying drivers

A member becomes a driver only after you verify them. Open the
account detail page and fill in:

- **Vehicle description** (e.g. "white sedan", "black motorcycle") —
  required, ≤ 80 characters, shown to matched riders and on the
  trusted-contact public page.
- **Vehicle plate** (optional, ≤ 40 characters). The plate is
  **not** shown on the public trusted-contact page; it stays inside
  the app and is visible only to the moderator team.

Click **Verify driver**. The driver can now post trips.

To revoke: open the same account, click **Revoke driver**. Future
trip instances for un-booked trips are hidden from the search
engine. Past bookings are left intact; cancelling them retroactively
would be unfair to the riders.

### Women-only eligibility

If `WOMEN_ONLY_TRIPS=true` on the server, the queue exposes two
extra buttons: **Grant women-only** and **Revoke women-only**. Use
these when a member self-identifies a need; the field is not
visible publicly and is never advertised.

---

## 5. Managing pickup places

Open `/moderation/places`. From there you can:

- **Add a place**: name (e.g. "Dhanmondi 27"), group label
  (e.g. "Dhanmondi"), kind (gate / hall / department / pickup /
  neighbourhood). Names are unique.
- **Delete a place**: this only works if no trip uses it. If a
  place is in active use, the route returns 404. Reach out to an
  operator and have the trip reassigned before deleting.

Places are public; their labels appear in search and trip pages.
Use stable, recognisable names — riders and drivers both rely on
them matching their lived experience.

---

## 6. Handling a safety report

Reports are submitted via the in-app **Report** button on a trip or
booking page. The report includes a free-text reason and a
category. The reporter's contact is on the detail page.

### When a report arrives

1. Read the reason carefully. It may include names or describe
   behaviour; treat it as confidential and do not share outside
   the moderation team.
2. Decide one of:
   - **No action** — the report is a misunderstanding. Click
     **Resolve** and add a note in your head, not in the system
     (we do not keep a notes field; the audit row is the only
     record).
   - **Suspend the reported user** — open their account page and
     click **Suspend**. The user is locked out immediately, even
     if they are mid-session. Their future bookings are cancelled
     and their future driver trips are hidden.
   - **Remove a problematic trip** — from the queue, click
     **Remove** on the affected trip. All future instances are
     cancelled, accepted riders are notified, and seats are
     freed. Past instances and past bookings are kept for the
     audit log.
3. Click **Resolve** on the report. The audit log now contains
   two rows: `report.resolve` and (if you took action)
   `user.suspend` or `trip.remove`.

### A safety report and a police complaint are different things

CampusRide is a tool for the campus. It is not a substitute for
emergency services. If the report describes an immediate risk,
advise the reporter to contact the campus emergency number
(displayed in the footer) or the local emergency number
(`EMERGENCY_NUMBER` in `.env`, default `999`). Do not investigate
beyond what the platform shows you.

---

## 7. Last-minute cancellations

The queue surfaces any booking where either side cancelled inside
`LAST_MINUTE_WINDOW_MINUTES` (default 120) of departure. These are
flagged, not punished — most are legitimate (sudden illness, family
emergency). Patterns to look for:

- The **same driver** with multiple last-minute cancels in a week.
  Speak to them. After the second one, consider revoking their
  driver status.
- The **same rider** with multiple last-minute cancels. Consider
  suspending after the third.

The `last_minute_cancel` flag is permanent on the booking record
and is visible in the audit log.

---

## 8. Post-trip problems

After every completed trip, the rider is shown a post-trip check.
A "Had a problem" answer lands in the queue. Resolve it the same
way you would resolve a report: open the item, read the answer,
take an action if needed, click **Resolve**. The audit row is the
record; there is no separate "handled" flag.

---

## 9. What is and is not in your reach

In scope for a moderator:

- Account status (approve / reject / suspend).
- Driver verification (vehicle description, plate).
- Women-only eligibility.
- Pickup places.
- Resolving reports, removing trips, resolving post-trip problems.

Out of scope for a moderator (escalate to the operator):

- Changing `MEMBER_CAP`, `RETENTION_DAYS`, `EMERGENCY_NUMBER`,
  `SUPPORTED_LANGS`, or any other setting. These are environment
  variables, changed at deploy time.
- Reading the audit log directly. The log is there for the
  operator; you don't need it to do your job.
- Bulk imports of places or users. The seed script is for the
  first pilot only.
- The Telegram bot or webhook. The operator owns that.

If you need something in the second list, contact the operator
running the deployment. The `EMERGENCY_NUMBER` should already
match the campus standard; if it does not, that is an operator
fix, not a moderator fix.
