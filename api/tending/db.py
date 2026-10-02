"""The async engine for live mode.

The inventory API's ``inventory.db`` already owns one lazily-created engine for this
process, and this package deliberately borrows it rather than creating a second.
Two pools in one API is two sets of connections against one Postgres, two places
to size, and two things to dispose on shutdown; the import is read-only and the
alternative is worse. If the app ever grows a proper lifespan-managed pool
(noted for the maintainers and the deployment in the weather engine's an earlier release pull
request and still open), both packages move to
it together.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from inventory.db import get_engine as _get_engine


def get_engine() -> AsyncEngine:
    return _get_engine()
