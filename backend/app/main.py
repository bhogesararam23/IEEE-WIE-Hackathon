"""Application entrypoint for the HerMediSafe API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Imported for the side effect: installing the global `deleted_at IS NULL`
# filter on every ORM SELECT. Must be imported before any query runs, and
# before the routers, so nothing can sneak a SELECT past it.
from app.core import soft_delete
from app.core.config import get_settings
from app.core.database import engine
from app.routers import (
    assistant,
    audit,
    auth,
    health,
    interactions,
    medicines,
    prescriptions,
    reminders,
    reports,
    users,
)
from app.services.health import check_database
from app.services.storage import local_storage_root

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Warm up on startup and release the connection pool on shutdown.

    The startup probe logs rather than raises: the container must stay up while
    Postgres finishes booting, otherwise compose restarts would crash-loop.
    ``/health`` is the authoritative dependency check.
    """
    settings = get_settings()
    logger.info(
        "Starting %s v%s (env=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    if settings.secret_key == _DEV_SECRET_KEY:
        # Loud rather than silent. A forgotten SECRET_KEY in production means
        # anyone can mint tokens for any user id.
        logger.warning(
            "SECRET_KEY is still the built-in development default -- "
            "every JWT this process signs is forgeable. Set SECRET_KEY."
        )
    if await check_database(settings.db_health_timeout):
        logger.info("Database connection established")
    else:
        logger.warning("Database not reachable yet; /health will report 'degraded'")
    soft_delete.install_soft_delete_filter()
    yield
    await engine.dispose()
    logger.info("Database connection pool disposed")


# Mirrors Settings.secret_key's default; compared in lifespan to warn.
_DEV_SECRET_KEY = "dev-insecure-change-me"


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
    )

    application = FastAPI(
        title=settings.app_name,
        summary="Backend services for HerMediSafe.",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Hackathon mode: open CORS so the Vite dev server can call the API from any
    # origin. Tighten `cors_origins` in Settings before shipping.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(users.router)
    application.include_router(prescriptions.router)
    application.include_router(medicines.router)
    application.include_router(interactions.router)
    application.include_router(reminders.router)
    application.include_router(reports.router)
    application.include_router(audit.router)
    application.include_router(assistant.router)

    # Uploaded prescriptions are served straight off disk. Only mounted when the
    # local backend is actually in use: a cloud backend has no directory to mount,
    # and mounting one anyway would serve an empty folder at /files while every
    # real URL pointed at a bucket.
    #
    # SECURITY: this mount is unauthenticated. Filenames are uuid4, so a URL is
    # not guessable, but anyone who does learn one can fetch the document. That is
    # acceptable for hashed demo data and not for real patient records -- the fix
    # is a token-checked endpoint (or presigned URLs), not a filename tweak.
    # Called out here because nothing in the response shape signals it.
    storage_root = local_storage_root()
    if storage_root is not None:
        application.mount(
            settings.storage_url_prefix,
            StaticFiles(directory=str(storage_root)),
            name="files",
        )
        logger.info(
            "Serving uploads from %s at %s", storage_root, settings.storage_url_prefix
        )
    else:
        logger.info(
            "Non-local storage backend; %s not mounted", settings.storage_url_prefix
        )

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
        }

    return application


app = create_app()
