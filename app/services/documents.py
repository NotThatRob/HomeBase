import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session, joinedload

from app.models.component import Component
from app.models.document import Document
from app.models.user import User

# Mass-assignment guard: only these keys flow from form data into the model.
DOCUMENT_ALLOWED_FIELDS = {"title", "doc_type", "notes"}

# Extension -> canonical MIME type. Drives both validation and the saved row.
DOCUMENT_EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

DOCUMENT_ALLOWED_EXTENSIONS = set(DOCUMENT_EXT_MIME.keys())

# Only these MIME types may be served by the /preview route. Office docs and
# anything else are forced through /download with Content-Disposition: attachment.
INLINE_PREVIEWABLE = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
    "text/plain",
    "text/markdown",
}

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10 MB


def _filter_allowed(data: dict, allowed: set) -> dict:
    """Return only the keys present in the allowed set."""
    return {k: v for k, v in data.items() if k in allowed}


def _safe_upload_path(upload_dir: str, relative_path: str) -> str | None:
    relative_path = relative_path.lstrip("/\\")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = Path(upload_dir).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return str(candidate)


def _validate_document_bytes(content: bytes, ext: str) -> bool:
    """Verify file content matches expected magic bytes for the given extension.

    Defense against ext/MIME spoofing — a .pdf containing PNG bytes (or worse,
    HTML/JS) is rejected before it ever lands on disk.
    """
    if ext in (".jpg", ".jpeg"):
        return content[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return content[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".gif":
        return content[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if ext in (".heic", ".heif"):
        # ISO BMFF "ftyp" box at offset 4, brand at offset 8.
        if content[4:8] != b"ftyp":
            return False
        brand = content[8:12]
        return brand in (
            b"heic",
            b"heix",
            b"heim",
            b"heis",
            b"hevc",
            b"hevx",
            b"mif1",
            b"msf1",
        )
    if ext == ".pdf":
        return content[:5] == b"%PDF-"
    if ext in (".docx", ".xlsx"):
        # Office Open XML files are zip containers.
        return content[:4] == b"PK\x03\x04"
    if ext in (".doc", ".xls"):
        # Legacy OLE2 compound document signature.
        return content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if ext in (".txt", ".md"):
        # No magic bytes for text — sanity-check that the first chunk has no
        # null bytes (a strong signal the file is binary).
        return b"\x00" not in content[:8192]
    return False


async def save_document(
    asset_id: uuid.UUID,
    file: UploadFile,
    upload_dir: str,
) -> dict:
    """Validate and persist an uploaded document to disk.

    Does NOT touch the database — returns a metadata dict that the caller
    feeds into ``create_document``. Splitting these makes the upload pipeline
    testable in isolation and lets routes batch multiple uploads atomically.
    """
    original = os.path.basename(file.filename) if file.filename else ""
    if not original:
        raise ValueError("Filename is required")

    ext = os.path.splitext(original)[1].lower()
    if ext not in DOCUMENT_ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension {ext!r} not allowed")

    content = await file.read(MAX_DOCUMENT_SIZE + 1)
    if len(content) == 0:
        raise ValueError("File is empty")
    if len(content) > MAX_DOCUMENT_SIZE:
        raise ValueError("File too large (max 10MB)")

    if not _validate_document_bytes(content, ext):
        raise ValueError("File content does not match expected format")

    mime_type = DOCUMENT_EXT_MIME[ext]

    # Random filename prevents user-controlled paths and crafted-extension XSS.
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    asset_dir = os.path.join(upload_dir, "documents", str(asset_id))
    os.makedirs(asset_dir, exist_ok=True)
    abs_path = os.path.join(asset_dir, safe_filename)
    with open(abs_path, "wb") as f:
        f.write(content)

    return {
        "file_path": f"documents/{asset_id}/{safe_filename}",
        "file_name": original,
        "mime_type": mime_type,
        "file_size": len(content),
    }


def create_document(
    db: Session,
    asset_id: uuid.UUID,
    data: dict,
    file_meta: dict,
    user: User,
    service_record_id: uuid.UUID | None = None,
    component_ids: list[uuid.UUID] | None = None,
) -> Document:
    filtered = _filter_allowed(data, DOCUMENT_ALLOWED_FIELDS)
    document = Document(
        asset_id=asset_id,
        service_record_id=service_record_id,
        uploaded_by_id=user.id,
        **filtered,
        **file_meta,
    )
    if component_ids:
        components = (
            db.query(Component)
            .filter(Component.id.in_(component_ids))
            .filter(Component.asset_id == asset_id)
            .all()
        )
        if len(components) != len(set(component_ids)):
            raise ValueError("Component does not belong to this asset")
        document.components = components
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def list_documents(
    db: Session,
    asset_id: uuid.UUID,
    service_record_id: uuid.UUID | None = None,
) -> list[Document]:
    query = (
        db.query(Document)
        .options(joinedload(Document.uploaded_by))
        .filter(Document.asset_id == asset_id)
    )
    if service_record_id is not None:
        query = query.filter(Document.service_record_id == service_record_id)
    return query.order_by(Document.uploaded_at.desc()).all()


def get_document(db: Session, document_id: uuid.UUID) -> Document | None:
    return (
        db.query(Document)
        .options(
            joinedload(Document.asset),
            joinedload(Document.uploaded_by),
            joinedload(Document.components),
            joinedload(Document.service_record),
        )
        .filter(Document.id == document_id)
        .first()
    )


def update_document(
    db: Session,
    document: Document,
    data: dict,
    component_ids: list[uuid.UUID] | None = None,
) -> Document:
    filtered = _filter_allowed(data, DOCUMENT_ALLOWED_FIELDS)
    for key, value in filtered.items():
        setattr(document, key, value)
    if component_ids is not None:
        components = (
            db.query(Component)
            .filter(Component.id.in_(component_ids))
            .filter(Component.asset_id == document.asset_id)
            .all()
        )
        if len(components) != len(set(component_ids)):
            raise ValueError("Component does not belong to this asset")
        document.components = components
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document: Document, upload_dir: str) -> None:
    """Delete a document row and remove its file from disk.

    Removes the database row and then the file; a missing file should not
    block the row delete (the disk could have been wiped, or a previous
    half-failure left an orphaned row). Failures here are logged-and-ignored.
    """
    abs_path = _safe_upload_path(upload_dir, document.file_path)
    if not abs_path:
        raise RuntimeError(f"unsafe path {upload_dir!r} {document.file_path!r}")
    db.delete(document)
    db.commit()
    try:
        Path(abs_path).unlink(missing_ok=True)
    except OSError:
        pass


def delete_asset_documents(db: Session, asset_id: uuid.UUID, upload_dir: str) -> None:
    """Best-effort cleanup of all document files for an asset.

    Used by callers that need to delete an asset and its files. The asset's
    ``cascade="all, delete-orphan"`` will remove the rows; this just removes
    the on-disk files first so they don't leak.
    """
    documents = (
        db.query(Document).filter(Document.asset_id == asset_id).all()
    )
    for doc in documents:
        abs_path = _safe_upload_path(upload_dir, doc.file_path)
        try:
            if abs_path:
                Path(abs_path).unlink(missing_ok=True)
        except OSError:
            pass
