# Scripts

Operational utilities for the Kalba backend. Each script is standalone and
uses the same `DATABASE_URL` / config as the running app — so it hits whatever
environment your env points to.

> **Safety note:** all scripts here run against the database/services your
> `.env.local` (or current shell env) is configured for. Double-check before
> running anything destructive against a non-local target.

Run from the `backend/` directory:

```
uv run python scripts/<name>.py [args...]
```

---

## `seed_workshops.py` — Seed random workshops for a trainer

Creates N random, non-colliding workshops in the next K days for a given
trainer. Useful for populating the calendar with realistic data during local
testing (calendar views, enrollment flow, filters, scrolling).

### What it does

- Looks up the trainer by **email** or **UUID**.
- Loads the trainer's existing future workshops in the horizon window and uses
  them as the collision baseline — **will not overlap existing sessions**.
- Generates N workshops with:
  - random title from a curated Polish list (yoga, medytacja, pilates, etc.),
  - description with hashtags (also populates the tag autocomplete index),
  - random duration: **30 / 45 / 60 / 75 / 90 minutes**,
  - random start aligned to a 15-min grid, hours 07:00–19:45,
  - random price (0 / 25 / 35 / 50 / 75) and max participants (5 / 8 / 10 / 12 / 15 / 20),
  - timezone `Europe/Warsaw`, reminder lead 60 min.
- Creates the matching `WorkshopRules` row (so the workshop is identical to one
  created via `POST /workshops/`).

### Requirements

- Trainer must exist and have role `TRAINER` — the script refuses
  regular users (warsztaty mogą tworzyć tylko trenerzy).
- Local Postgres must be reachable (`docker compose -f
  docker-compose.local.yml up -d`) and migrations applied (`uv run alembic
  upgrade head`).
- `APP_ENV=local` — the script hard-refuses any other environment to keep
  random seed data out of dev/stage/prod. `--force` overrides this; use only
  if you know what you're doing.

### Usage

```bash
# Default: 20 workshops in the next 90 days
uv run python scripts/seed_workshops.py --user trainer@example.com

# Lots of data, longer horizon, reproducible run
uv run python scripts/seed_workshops.py \
  --user trainer@example.com \
  --count 50 \
  --horizon-days 120 \
  --seed 42

# By UUID instead of email
uv run python scripts/seed_workshops.py \
  --user 8ea02008-2aa1-4817-b6a0-dd30ef6dfe90 \
  --count 30
```

### Arguments

| Flag | Required | Default | Meaning |
|---|---|---|---|
| `--user` | yes | — | trainer email or UUID |
| `--count` | no | `20` | how many workshops to create |
| `--horizon-days` | no | `90` | days into the future to spread over |
| `--seed` | no | random | seed for reproducible runs (same inputs → same plan) |
| `--force` | no | off | required to run when `APP_ENV != local` (escape hatch) |

### Output

```
Trainer: trainer@example.com (8ea02008-...); 3 workshops already in the next 90 days — will plan around them.
  [  1/20] Yoga flow                  Mon 2026-05-31 09:15 (60 min)
  [  2/20] Praca z oddechem           Wed 2026-06-03 18:30 (45 min)
  ...
Created 20 workshops for trainer@example.com.
```

If the calendar is too dense to fit `--count` more workshops without collision,
the script reports how many it managed to create and stops (it doesn't loop
forever). Tune `--horizon-days` up or `--count` down.

### Cleaning up

Workshops created by this script are normal records — delete them via the
trainer account in the app (soft-delete) or via SQL:

```sql
UPDATE workshop
SET deleted_at = now()
WHERE trainer_id = '<trainer-uuid>' AND start_time > now();
```

---

## `test_daily.py` — Daily.co integration smoke test

End-to-end check that the Daily.co API key and domain are configured
correctly: creates a test room, fetches it, and deletes it. Run after rotating
`DAILY_API_KEY` or when troubleshooting video issues.

```
uv run python scripts/test_daily.py
```

---

## `setup_daily_webhook.py` — Register the Daily.co → backend webhook

One-time setup (per environment) to register the webhook that delivers
`participant.joined` and friends to `/api/v1/video/webhooks/daily`. Outputs
the HMAC secret to store in `DAILY_WEBHOOK_SECRET`.

```
uv run python scripts/setup_daily_webhook.py \
  --url https://backend-kalba.fly.dev/api/v1/video/webhooks/daily
```

See the script's docstring (`--help`) for the second mode where you provide
your own HMAC secret.

---

## `init-test-db.sql`

Initialization SQL for the local test Postgres container (creates the
`kalba_test` database). Not invoked directly — picked up by docker-compose.

---

## `AIAgents/`

Configuration for Claude Code / Copilot agents and skills used by this repo
(code review panel, ship workflows, etc.). Not runtime scripts — see
`AIAgents/Claude/CLAUDE.md` for details.
