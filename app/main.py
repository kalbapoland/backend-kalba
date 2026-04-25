import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.services.scheduler import start_reminder_loop_task

# Configure root logger to ensure INFO logs from app are emitted
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    reminder_task = start_reminder_loop_task()
    try:
        yield
    finally:
        # Shutdown
        if reminder_task is not None:
            reminder_task.cancel()
            results = await asyncio.gather(reminder_task, return_exceptions=True)
            for outcome in results:
                if isinstance(outcome, BaseException) and not isinstance(
                    outcome, asyncio.CancelledError
                ):
                    logging.getLogger(__name__).error(
                        "Reminder loop terminated with error during shutdown: %s",
                        outcome,
                        exc_info=outcome,
                    )


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Kalba - Meditation & Workshop API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_router)

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
