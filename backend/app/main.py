"""FastAPI application factory and entrypoint.

This wires together configuration, middleware, routers, and a startup hook
that bootstraps the first administrator so the platform is usable immediately
after a fresh deployment.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories.user import UserRepository
from app.services.user import UserService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _bootstrap_first_admin() -> None:
    """Ensure a default ADMIN account exists on first boot."""
    async with AsyncSessionLocal() as session:
        service = UserService(UserRepository(session))
        created = await service.ensure_first_admin(
            email=settings.FIRST_ADMIN_EMAIL,
            username=settings.FIRST_ADMIN_USERNAME,
            password=settings.FIRST_ADMIN_PASSWORD,
        )
        if created is not None:
            await session.commit()
            logger.info("Bootstrapped first admin: %s", created.email)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown logic."""
    logger.info("Starting %s (%s)", settings.PROJECT_NAME, settings.ENVIRONMENT)
    await _bootstrap_first_admin()
    yield
    logger.info("Shutting down %s", settings.PROJECT_NAME)


def create_app() -> FastAPI:
    """Application factory (testable and reusable)."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o) for o in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", tags=["root"], summary="Service banner")
    async def root() -> dict[str, str]:
        return {
            "service": settings.PROJECT_NAME,
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


app = create_app()
