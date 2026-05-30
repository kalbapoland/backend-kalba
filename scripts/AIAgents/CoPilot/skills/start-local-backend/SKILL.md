---
name: start-local-backend
description: 'Uruchamia backend Kalba lokalnie na Windows (Docker Postgres + migracje + FastAPI). Uzyj, gdy trzeba szybko postawic API do developmentu lub testow manualnych.'
argument-hint: 'local | dev | remote (opcjonalnie)'
user-invocable: true
---

# Start Local Backend

Use this skill when the user asks to run backend locally.

## Prerequisites

- Docker Desktop is running.
- `uv` is installed.
- Work from backend repository root (for example `E:/Projects/Kalba/backend`).

## Argument Variants

- `local` (default): start local Postgres + migrations + local API on `127.0.0.1:8000`.
- `dev`: same as `local`, but use `APP_ENV=dev` before migrations/server start.
- `remote`: do not start local backend; verify and use deployed backend instead.

`remote` quick check:

```powershell
Invoke-WebRequest -Uri https://backend-kalba.fly.dev/health -UseBasicParsing
```

`dev` env setup (PowerShell):

```powershell
$env:APP_ENV = "dev"
```

## Default Local Flow

1. Go to backend directory.

```powershell
cd E:/Projects/Kalba/backend
```

2. Start PostgreSQL container for local development.

```powershell
docker compose -f docker-compose.local.yml up -d
```

3. Apply database migrations.

```powershell
uv run alembic upgrade head
```

4. Start FastAPI with auto-reload.

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

## Verification

- API health/docs should be available on:
  - `http://127.0.0.1:8000/health`
  - `http://127.0.0.1:8000/docs`

## First-Run Dependency Sync (if needed)

If dependencies are missing, run once before migrations:

```powershell
uv sync
```

## Stop Services

- Stop API server with `Ctrl+C` in the running terminal.
- Stop local Postgres container:

```powershell
docker compose -f docker-compose.local.yml down
```

## Troubleshooting

- Migration fails with DB connection error:
  - confirm Docker is running,
  - check container status: `docker compose -f docker-compose.local.yml ps`.
- Port `8000` busy:
  - run server on different port, e.g. `--port 8001`.
- Env-related startup errors:
  - ensure required variables are present in local env files used by `app/core/config.py`.
