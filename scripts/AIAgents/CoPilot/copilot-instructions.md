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

## Rules

- Business logic belongs in `services/`, never in route handlers
- Never use `dict()` for Pydantic serialization — use `model_dump()`
- Never use synchronous DB calls — always `await`
- Never log JWTs, Google tokens, or user PII
- Never hardcode secrets — all secrets via environment variables
