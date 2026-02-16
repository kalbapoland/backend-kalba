# Kalba - Meditation & Workshop API

A FastAPI backend for a mobile-first meditation and workshop platform. Users authenticate via Google, browse workshops, and trainers can create and manage sessions.

## Tech Stack

- **FastAPI** - async web framework
- **SQLModel** - ORM (SQLAlchemy 2.0 + Pydantic)
- **PostgreSQL** - database (asyncpg driver)
- **Alembic** - database migrations
- **Google OAuth2** - passwordless authentication via ID tokens
- **JWT** - session tokens issued after Google verification
- **uv** - package and environment management

## Project Structure

```
app/
├── api/v1/
│   ├── auth.py          # POST /api/v1/auth/google
│   ├── users.py         # GET  /api/v1/users/me
│   ├── workshops.py     # GET/POST /api/v1/workshops/
│   └── router.py
├── core/
│   ├── config.py        # Settings with 4 environment profiles
│   └── security.py      # JWT + Google token verification
├── models/
│   ├── user.py          # User, TrainerProfile, UserRole
│   └── workshop.py      # Workshop
├── db.py                # Async engine + session dependency
└── main.py              # App factory
migrations/              # Alembic migrations
```

## Authentication Flow

1. The mobile app authenticates with Google and obtains an `id_token`.
2. The app sends the token to `POST /api/v1/auth/google`.
3. The backend verifies it with Google, creates the user if new, and returns a local JWT.
4. All subsequent requests use the JWT as a `Bearer` token.

## Environments

Set `APP_ENV` to switch between profiles. Each loads its own `.env.{APP_ENV}` file:

| Value   | Description              |
|---------|--------------------------|
| `local` | Development on your machine (default) |
| `dev`   | Development server       |
| `stage` | Pre-production testing   |
| `prod`  | Live production          |

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Docker](https://docs.docker.com/get-docker/)

### Install dependencies

```bash
uv sync
```

### Configure environment

Copy and edit the local env file:

```bash
cp .env.local .env.local  # already provided as a template
```

Update `JWT_SECRET_KEY` and `GOOGLE_CLIENT_ID` with your values.

### Database (Docker)

Start the local PostgreSQL database:

```bash
docker compose -f docker-compose.local.yml up -d
```

Stop the database (data is preserved):

```bash
docker compose -f docker-compose.local.yml down
```

Stop and wipe all data:

```bash
docker compose -f docker-compose.local.yml down -v
```

### Migrations (Alembic)

Apply all pending migrations:

```bash
uv run python -m alembic upgrade head
```

Generate a new migration after model changes:

```bash
uv run python -m alembic revision --autogenerate -m "describe your change"
```

Rollback the last migration:

```bash
uv run python -m alembic downgrade -1
```

### Start the server

```bash
uv run uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. Open `http://localhost:8000/docs` for interactive Swagger documentation.

## API Endpoints

| Method | Path                    | Auth     | Description                    |
|--------|-------------------------|----------|--------------------------------|
| GET    | `/health`               | No       | Health check                   |
| POST   | `/api/v1/auth/google`   | No       | Exchange Google ID token for JWT |
| GET    | `/api/v1/users/me`      | Bearer   | Get current user profile       |
| GET    | `/api/v1/workshops/`    | No       | List upcoming workshops        |
| POST   | `/api/v1/workshops/`    | Bearer (trainer only) | Create a workshop |

## Deployment (Fly.io)

The app is containerized with Docker and configured for [Fly.io](https://fly.io) deployment.

### Prerequisites

- [Fly CLI](https://fly.io/docs/flyctl/install/) installed
- Authenticated: `fly auth login`

### First-time setup

1. **Create the app** (from the project root):

```bash
fly launch --no-deploy
```

This creates the app on your Fly.io account and updates `fly.toml` with the assigned app name. The `app` field in `fly.toml` ties all future deploys to that specific app/account.

2. **Create and attach a Postgres database**:

```bash
fly postgres create --name kalba-db --region ams
fly postgres attach kalba-db
```

This automatically sets the `DATABASE_URL` secret on the app.

3. **Set secrets** (environment variables):

```bash
fly secrets set \
  JWT_SECRET_KEY="$(openssl rand -hex 32)" \
  GOOGLE_CLIENT_ID="your-google-client-id" \
  GOOGLE_IOS_CLIENT_ID="your-ios-client-id" \
  DAILY_API_KEY="your-daily-api-key" \
  DAILY_DOMAIN="kalba.daily.co"
```

### Deploy

```bash
fly deploy
```

Alembic migrations run automatically on each deploy before the server starts.

### Production URL

The app is available at: `https://backend-kalba.fly.dev`

- Health check: `https://backend-kalba.fly.dev/health`
- Swagger docs: `https://backend-kalba.fly.dev/docs`

### Useful commands

```bash
fly status              # App status and machines
fly logs                # Stream live logs
fly ssh console         # SSH into the running machine
fly secrets list        # List set secrets (values hidden)
fly postgres connect kalba-db  # Connect to the database via psql
```

### How Fly.io knows where to deploy

The `app` field in `fly.toml` identifies the target app. When you run `fly launch`, it creates an app under your currently authenticated account (`fly auth whoami`) and writes the app name into `fly.toml`. All subsequent `fly deploy` commands read this name and deploy to that app. If you need to switch accounts, run `fly auth login` again.
