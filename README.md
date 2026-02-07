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
