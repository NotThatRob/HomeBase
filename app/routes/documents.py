import os
import urllib.parse
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.document import DOC_TYPES
from app.services.assets import get_asset
from app.services.components import list_components
from app.services.documents import (
    INLINE_PREVIEWABLE,
    create_document,
    delete_document,
    get_document,
    save_document,
    update_document,
)

router = APIRouter(tags=["documents"])


def _document_response_headers(filename: str, attachment: bool) -> dict:
    """Build the security headers used by /preview and /download.

    The two routes share the same hardening: nosniff, locked-down CSP,
    no-referrer, and short private cache. The only difference is the
    Content-Disposition disposition (inline vs attachment).
    """
    disp = "attachment" if attachment else "inline"
    encoded = urllib.parse.quote(filename)
    return {
        # RFC 6266 — filename* with UTF-8 encoding handles unicode safely.
        "Content-Disposition": f"{disp}; filename*=UTF-8''{encoded}",
        "X-Content-Type-Options": "nosniff",
        # No JS, no plugins; only same-origin images and objects (PDFs) allowed.
        "Content-Security-Policy": (
            "default-src 'none'; img-src 'self'; object-src 'self'; "
            "style-src 'unsafe-inline'"
        ),
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, max-age=300",
    }


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


def _load_document_or_404(
    db: Session, document_id: uuid.UUID, user, require_owner: bool = False
):
    """Common loader: fetch document, fetch parent asset, run access check."""
    document = get_document(db, document_id)
    if not document:
        return None, HTMLResponse("Document not found", status_code=404)
    asset = document.asset
    if not asset:
        return None, HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=require_owner)
    return document, None


# ----- Asset-scoped create -----------------------------------------------------


@router.get("/assets/{asset_id}/documents/new", response_class=HTMLResponse)
def document_new(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    if asset.status == "retired":
        return HTMLResponse(
            "Cannot add documents to retired assets", status_code=400
        )
    components = list_components(db, asset_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "documents/form.html",
        {
            "asset": asset,
            "components": components,
            "doc_types": DOC_TYPES,
            "user": user,
        },
    )


@router.post("/assets/{asset_id}/documents")
async def document_create(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    if asset.status == "retired":
        return HTMLResponse(
            "Cannot add documents to retired assets", status_code=400
        )

    raw_form = await request.form()
    data = dict(raw_form)
    file = data.pop("file", None)
    component_ids_raw = raw_form.getlist("component_ids")
    data.pop("component_ids", None)

    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    if not file or not getattr(file, "filename", ""):
        return HTMLResponse("A file is required", status_code=400)

    settings = get_settings()
    try:
        file_meta = await save_document(asset.id, file, settings.upload_dir)
    except ValueError as exc:
        return HTMLResponse(f"Upload rejected: {exc}", status_code=400)

    # Default the title to the filename if the user left it blank.
    if not data.get("title"):
        data["title"] = file_meta["file_name"]
    if not data.get("doc_type"):
        data["doc_type"] = "other"

    try:
        component_ids = [uuid.UUID(v) for v in component_ids_raw] if component_ids_raw else None
    except ValueError:
        return HTMLResponse("Invalid component id", status_code=400)

    try:
        document = create_document(
            db, asset.id, data, file_meta, user, component_ids=component_ids
        )
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/documents/{document.id}", status_code=303)


# ----- Document detail / preview / download -----------------------------------


@router.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user)
    if error:
        return error
    return request.app.state.templates.TemplateResponse(
        request,
        "documents/detail.html",
        {
            "document": document,
            "asset": document.asset,
            "user": user,
            "inline_previewable": document.mime_type in INLINE_PREVIEWABLE,
        },
    )


@router.get("/documents/{document_id}/preview")
def document_preview(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user)
    if error:
        return error

    # /preview is strictly for safe inline types. Office docs go via /download.
    if document.mime_type not in INLINE_PREVIEWABLE:
        return HTMLResponse(
            "This document type cannot be previewed inline", status_code=400
        )

    settings = get_settings()
    abs_path = _safe_upload_path(settings.upload_dir, document.file_path)
    if not abs_path or not os.path.isfile(abs_path):
        return HTMLResponse("File not found", status_code=404)

    return FileResponse(
        abs_path,
        media_type=document.mime_type,
        headers=_document_response_headers(document.file_name, attachment=False),
    )


@router.get("/documents/{document_id}/download")
def document_download(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user)
    if error:
        return error

    settings = get_settings()
    abs_path = _safe_upload_path(settings.upload_dir, document.file_path)
    if not abs_path or not os.path.isfile(abs_path):
        return HTMLResponse("File not found", status_code=404)

    return FileResponse(
        abs_path,
        media_type="application/octet-stream",
        headers=_document_response_headers(document.file_name, attachment=True),
    )


# ----- Edit / Delete -----------------------------------------------------------


@router.get("/documents/{document_id}/edit", response_class=HTMLResponse)
def document_edit(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user, require_owner=True)
    if error:
        return error
    components = list_components(db, document.asset_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "documents/edit_form.html",
        {
            "document": document,
            "asset": document.asset,
            "components": components,
            "doc_types": DOC_TYPES,
            "user": user,
        },
    )


@router.post("/documents/{document_id}/edit")
async def document_update(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user, require_owner=True)
    if error:
        return error

    raw_form = await request.form()
    data = dict(raw_form)
    component_ids_raw = raw_form.getlist("component_ids")
    data.pop("component_ids", None)

    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    try:
        component_ids = [uuid.UUID(v) for v in component_ids_raw] if component_ids_raw else []
    except ValueError:
        return HTMLResponse("Invalid component id", status_code=400)

    try:
        update_document(db, document, data, component_ids=component_ids)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/documents/{document.id}", status_code=303)


@router.post("/documents/{document_id}/delete")
def document_delete(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    document, error = _load_document_or_404(db, document_id, user, require_owner=True)
    if error:
        return error
    asset_id = document.asset_id
    settings = get_settings()
    delete_document(db, document, settings.upload_dir)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)
