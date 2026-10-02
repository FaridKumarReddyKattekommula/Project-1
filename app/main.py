import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import repository as repo
from app.api.routes import router
from app.config import Settings, get_settings
from app.db import connect
from app.db.seed import seed
from app.errors import register_error_handlers
from app.observability import configure_logging, request_context

log = logging.getLogger(__name__)


def resolve_as_of(settings: Settings) -> datetime:
    if settings.as_of is not None:
        as_of = settings.as_of
        return as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    conn = connect(settings.database_path)
    try:
        latest = repo.latest_activity(conn)
    finally:
        conn.close()
    return latest or datetime.now(UTC)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.database_path.exists():
            if not settings.auto_seed:
                raise RuntimeError(
                    f"database not found at {settings.database_path}; run `python -m app.db.seed`"
                )
            seed(settings.database_path, settings.data_dir)
        app.state.as_of = resolve_as_of(settings)
        log.info("ready: database=%s as_of=%s", settings.database_path, app.state.as_of.isoformat())
        yield

    app = FastAPI(
        title="Circle Recommendations API",
        version="1.0.0",
        description=(
            "Recommends Lean In Circles a member should join, ranked, with a short "
            "member-facing explanation for each."
        ),
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    app.middleware("http")(request_context)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )
    register_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
