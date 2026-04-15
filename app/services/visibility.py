"""Shared asset visibility helper.

Any query that reads Asset-scoped data must filter through this so that
a user cannot see another user's personal assets (or rows linked to
them). Leaking a personal asset across user boundaries is a privacy
bug, so this helper is the single source of truth.
"""

from sqlalchemy import or_, select

from app.models.asset import Asset
from app.models.user import User


def visible_asset_ids(user: User):
    """Scalar ``select()`` of asset IDs the user is allowed to see.

    Returned as a ``select`` (not a subquery) so it composes cleanly
    with ``column.in_(...)`` — SQLAlchemy 2.x warns on subquery
    coercion in that position.
    """
    return select(Asset.id).where(or_(Asset.visibility == "shared", Asset.created_by_id == user.id))
