"""The async engine, the session factory, and the per-request dependency.

WHAT: builds one engine per application and hands out one ``AsyncSession`` per
      request.
WHY:  ``expire_on_commit=False`` is the setting that matters and it is a trap
      documented in the control rulebook: with the default, touching any attribute
      after a commit triggers lazy I/O outside the session, which raises at runtime
      and not in tests. Every service here commits and then returns objects the
      route serialises, so the default would break most of them.
HOW:  ``Database`` is created in the application factory and stored on app state.
      Routes depend on ``session`` and never construct one themselves.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the engine and the session factory for one application."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        # echo is False and there is no debug switch for it on purpose. SQLAlchemy's
        # echo writes every statement AND its bound parameters to the log — which
        # for this schema means subscription tokens and decrypted secrets on disk.
        # "Temporarily, while debugging" is exactly the case the charter's
        # no-logging rule refuses to make an exception for.
        self._engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            # Recycle before the typical cloud idle-timeout so a node operation
            # after a quiet night does not fail once on a stale connection.
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self._sessions = async_sessionmaker(
            self._engine, expire_on_commit=False, autoflush=False
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def dispose(self) -> None:
        """Close the pool. Called on application shutdown."""
        await self._engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        """One session per request, rolled back if the handler raised.

        The rollback is explicit rather than relying on the context manager's
        close: a service that raised partway through a node operation must not
        leave half of it committed, because a half-configured node is the state
        core invariants §4 says must never be reported as active.
        """
        async with self._sessions() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
