# Kalba — Backend

## Tech Stack

Python 3.13, FastAPI (async), PostgreSQL 16, SQLModel ORM, Alembic migrations.
Package manager: uv. Deployed to Fly.io (Amsterdam).

## Architecture

- `app/api/v1/` — route handlers (thin; no business logic here)
- `app/services/` — business logic
- `app/models/` — SQLModel DB models + Pydantic DTOs
- `app/core/config.py` — Pydantic settings from env
- `app/core/security.py` — JWT creation/validation, Google token verification
- `app/db.py` — async SQLAlchemy engine + session `Depends`

## Code Conventions

- Async/await throughout — never call blocking I/O in an async handler
- Type annotations on every function signature (params + return type)
- Pydantic models for all request/response DTOs (`WorkshopCreate`, `WorkshopRead`, etc.)
- SQLModel for DB table models
- Use `T | None` not `Optional[T]` (Python 3.10+ union syntax)
- HTTP errors via `HTTPException` with meaningful `detail` string
- Auth dependency: `current_user: User = Depends(get_current_user)`
- Role check inline in handler: `if current_user.role != UserRole.TRAINER: raise HTTPException(403, ...)`

## Common Patterns

```python
# Route handler
@router.post("/{id}/join", response_model=JoinResponse)
async def join_workshop(
    id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> JoinResponse:
    ...

# DB query
result = await session.execute(select(Workshop).where(Workshop.id == id))
workshop = result.scalar_one_or_none()
if not workshop:
    raise HTTPException(status_code=404, detail="Workshop not found")

# Pydantic model
class WorkshopCreate(SQLModel):
    title: str
    description: str | None = None
    capacity: int
    starts_at: datetime
```

## Roles

- `UserRole.USER` — default; can join workshops
- `UserRole.TRAINER` — can create/update/delete workshops, hosts video calls

## Design Document

Cross-cutting product/design decisions live in the frontend repo at
`../frontend/docs/DESIGN.md` (single source of truth across both repos).
Consult it before designing new features and update it whenever a
backend-visible decision is made or a feature ships.

## Pre-Commit Code Review Workflow

Before committing changes, a multi-agent code review should be performed.

The entry point is `.github/prompts/code-reviewer.prompt.md` — a **manager** prompt that does not review code itself. For large diffs, it coordinates **max 2 independent reviewers**, each covering a subset of categories:

- `review-risk-surface.prompt.md` — Correctness, Security, API Design
- `review-quality-architecture.prompt.md` — Architecture, Documentation, Coding Standards, Performance, Tests

For small diffs, the manager may route to `review-single-pass.prompt.md`.

The manager dispatches the staged diff as clean independent passes, collects each reviewer report, and merges them into a single consolidated review with deduplication and strictest-severity-wins rules.

In Copilot Chat: reference the manager prompt file and provide the staged diff (`git diff --cached`). The manager handles the orchestration — you do not need to invoke specialists individually unless you want a focused review of one domain.

The reviewer reports findings and the developer decides whether to commit, fix issues first, or explicitly skip the review. This step is skipped only when the developer explicitly says so.

## Rules

- Business logic belongs in `services/`, never in route handlers
- Never use `dict()` for Pydantic serialization — use `model_dump()`
- Never use synchronous DB calls — always `await`
- Never log JWTs, Google tokens, or user PII
- Never hardcode secrets — all secrets via environment variables
