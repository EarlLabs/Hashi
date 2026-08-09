"""Request-scoped dependencies.

WHAT: the ``AsyncSession`` dependency every route uses.
WHY:  the session factory lives on application state, so the dependency has to reach
      it through the request rather than importing a module-level engine. That is
      what lets tests build an app against their own database without patching
      anything.
HOW:  ``session: AsyncSession = Depends(session_dependency)``. One session per
      request, per the control rulebook.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def session_dependency(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session for this request."""
    database = request.app.state.database
    async for session in database.session():
        yield session
