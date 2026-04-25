# Kalba — Backend

## Project Overview

REST API for a meditation & workshop platform with live video sessions.
Python 3.13 + FastAPI (async), PostgreSQL 16, SQLModel ORM, Alembic migrations.
Deployed to Fly.io (Amsterdam region). Package manager: **uv**.

## Architecture

```
app/
├── main.py                  # FastAPI app factory, CORS, /health
├── db.py                    # Async SQLAlchemy engine + session dependency
├── core/
│   ├── config.py            # Pydantic settings (reads from env / .env.{APP_ENV})
│   └── security.py          # JWT creation/validation, Google token verification
├── models/                  # SQLModel table + Pydantic DTO definitions
│   ├── user.py              # User, TrainerProfile, UserRole
│   ├── workshop.py          # Workshop, WorkshopCreate/Update/Read
│   ├── auth.py              # GoogleAuthRequest, AuthResponse
│   └── video.py             # WorkshopRules, WorkshopParticipant, Daily.co DTOs
├── api/v1/
│   ├── router.py            # Main v1 router (prefix: /api/v1)
│   ├── auth.py              # POST /auth/google
│   ├── users.py             # GET /users/me
│   ├── workshops.py         # CRUD /workshops/
│   └── video.py             # POST /video/workshops/{id}/join, host-action, webhook
└── services/
    └── daily.py             # DailyService — Daily.co REST API wrapper
```

### Auth Flow

1. Frontend exchanges Google ID token → `POST /api/v1/auth/google`
2. Backend verifies against Google's tokeninfo endpoint
3. Supports 3 client IDs: web, iOS, Android (`GOOGLE_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID`)
4. Returns JWT (HS256, 7-day expiry)

### Roles

- `USER` — default, can join workshops
- `TRAINER` — can create/update/delete workshops, is host in video sessions

## Dev Commands

### Run locally (Docker)

```bash
docker compose -f docker-compose.local.yml up -d   # start Postgres
uv run alembic upgrade head                         # run migrations
uv run uvicorn app.main:app --reload --port 8000    # start server
```

### Migrations

```bash
uv run alembic revision --autogenerate -m "description"   # create migration
uv run alembic upgrade head                               # apply
uv run alembic downgrade -1                               # rollback one
```

### Tests

```bash
uv run pytest -q --tb=short
```

> Tests require a running PostgreSQL. Set `DATABASE_URL` env var or use Docker Compose.
> CI runs pytest automatically on PR and push to `main` (see `.github/workflows/ci-backend.yml`).

## Environment Variables

| Variable | Description |
|---|---|
| `APP_ENV` | `local` / `dev` / `stage` / `prod` |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Secret for signing JWTs |
| `GOOGLE_CLIENT_ID` | Google OAuth — web client |
| `GOOGLE_IOS_CLIENT_ID` | Google OAuth — iOS client |
| `GOOGLE_ANDROID_CLIENT_ID` | Google OAuth — Android client |
| `DAILY_API_KEY` | Daily.co API key |
| `DAILY_DOMAIN` | Daily.co domain (e.g. `kalba.daily.co`) |

Local development: copy `.env.local.example` → `.env.local` and fill in values.

## Deployment

- **Platform:** Fly.io (`backend-kalba`, region: `ams`)
- **Trigger:** push to `main` → GitHub Actions (`fly-deploy.yml`) → `flyctl deploy`
- **Migrations:** run automatically inside Docker CMD before uvicorn starts
- **Secrets:** managed via `fly secrets set` — never commit real values

```bash
fly secrets list --app backend-kalba
fly secrets set KEY=value --app backend-kalba
fly logs --app backend-kalba
```

## CI

`.github/workflows/ci-backend.yml` — runs on PR and push to `main`:
1. Starts PostgreSQL 16 service container
2. Installs Python 3.13 + uv
3. Runs Alembic migrations
4. Runs pytest

## Design Document

Cross-cutting product/design decisions, current capabilities, known
limitations, and future improvement ideas live in the **frontend** repo at
`../frontend/docs/DESIGN.md` (single source of truth across both repos —
the design is product-driven, not platform-specific). **Consult it before
designing new features and update it whenever a backend-visible decision
is made or a feature ships.** Keep entries concise and dated.

## Git Conventions

- Branch names prefixed with developer name, e.g. `banaszki/feature-name`
- **Always create a new branch for every new feature or fix** — never commit directly to `main`
- Branch protection is enabled on `main` — direct pushes are blocked
- Never push directly to `main` — all changes via pull request
- PR requires approval from the other developer before merge
- CI (pytest + TypeScript) must pass before merge is allowed

## Code Style

- Python 3.13, async/await throughout
- Type annotations on all functions
- Pydantic models for all request/response DTOs
- SQLModel for DB models (combines SQLAlchemy + Pydantic)
- Keep business logic in `services/`, routing logic in `api/`
