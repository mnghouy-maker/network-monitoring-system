"""Async database engine and session factory.

We use SQLAlchemy 2.0's async engine with ``asyncpg``. A single engine is
created per process; sessions are created per request and yielded by the
``get_db`` dependency in ``app.core.dependencies``.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    str(settings.DATABASE_URI),
    echo=settings.DEBUG,
    pool_pre_ping=True,  # transparently recycle dead connections
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # objects stay usable after commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session (unit of work).

    The session is committed when the request handler returns successfully and
    rolled back if it raises, so endpoints/services never have to manage
    transactions manually. The session is always closed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
