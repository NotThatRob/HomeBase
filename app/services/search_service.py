"""Global search across assets, service records, and documents.

The query approach is deliberately simple — case-insensitive ``ILIKE
'%term%'`` against the relevant text columns. At 2-user scale there is
no need for ``tsvector``/GIN indexes; the whole search would fit on
one flash page. If the row counts grow past a few thousand we can
swap in ``websearch_to_tsquery`` without changing the route layer.

All queries are scoped through ``visible_asset_ids`` so personal
assets owned by another user cannot leak into results.
"""

from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.document import Document
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.services.validation import MAX_SEARCH_QUERY, escape_like
from app.services.visibility import visible_asset_ids

MIN_QUERY_LEN = 2
PER_ENTITY_LIMIT = 25
LIKE_ESCAPE = "\\"


def global_search(db: Session, user: User, query: str) -> dict:
    """Return matching assets, service records, and documents for ``query``.

    Returns an empty-but-well-formed dict when the query is too short
    so callers don't need to special-case the shape.
    """
    q = (query or "").strip()[:MAX_SEARCH_QUERY]
    if len(q) < MIN_QUERY_LEN:
        return {"assets": [], "records": [], "documents": [], "query": q, "total": 0}

    pattern = f"%{escape_like(q)}%"
    visible = visible_asset_ids(user)

    asset_rows = (
        db.query(Asset)
        .filter(Asset.id.in_(visible))
        .filter(
            Asset.name.ilike(pattern, escape=LIKE_ESCAPE)
            | Asset.make.ilike(pattern, escape=LIKE_ESCAPE)
            | Asset.model_name.ilike(pattern, escape=LIKE_ESCAPE)
            | Asset.notes.ilike(pattern, escape=LIKE_ESCAPE)
            | Asset.serial_number.ilike(pattern, escape=LIKE_ESCAPE)
        )
        .order_by(Asset.name.asc())
        .limit(PER_ENTITY_LIMIT)
        .all()
    )

    record_rows = (
        db.query(ServiceRecord)
        .options(joinedload(ServiceRecord.asset))
        .filter(ServiceRecord.asset_id.in_(visible))
        .filter(
            ServiceRecord.title.ilike(pattern, escape=LIKE_ESCAPE)
            | ServiceRecord.description.ilike(pattern, escape=LIKE_ESCAPE)
            | ServiceRecord.next_service_notes.ilike(pattern, escape=LIKE_ESCAPE)
            | ServiceRecord.vendor.ilike(pattern, escape=LIKE_ESCAPE)
        )
        .order_by(ServiceRecord.service_date.desc())
        .limit(PER_ENTITY_LIMIT)
        .all()
    )

    document_rows = (
        db.query(Document)
        .options(joinedload(Document.asset))
        .filter(Document.asset_id.in_(visible))
        .filter(
            Document.title.ilike(pattern, escape=LIKE_ESCAPE)
            | Document.notes.ilike(pattern, escape=LIKE_ESCAPE)
            | Document.file_name.ilike(pattern, escape=LIKE_ESCAPE)
        )
        .order_by(Document.uploaded_at.desc())
        .limit(PER_ENTITY_LIMIT)
        .all()
    )

    return {
        "assets": asset_rows,
        "records": record_rows,
        "documents": document_rows,
        "query": q,
        "total": len(asset_rows) + len(record_rows) + len(document_rows),
    }
