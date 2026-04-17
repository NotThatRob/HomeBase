import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.maintenance_task import MaintenanceTask
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.models.vehicle_meta import VehicleMeta

CATEGORIES = ["vehicle", "appliance", "home_system", "tech", "furniture", "other"]
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

ASSET_ALLOWED_FIELDS = {
    "name", "category", "subcategory", "make", "model_name", "year",
    "serial_number", "purchase_date", "purchase_price", "purchase_vendor",
    "warranty_expiration", "warranty_notes", "location", "notes",
}


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


def list_assets(
    db: Session,
    user: User,
    category: str | None = None,
    include_retired: bool = False,
) -> list[Asset]:
    query = db.query(Asset).options(joinedload(Asset.created_by))
    if not include_retired:
        query = query.filter(Asset.status != "retired")
    # Only show shared assets + user's own personal assets
    query = query.filter(
        or_(Asset.visibility == "shared", Asset.created_by_id == user.id)
    )
    if category:
        query = query.filter(Asset.category == category)
    return query.order_by(Asset.created_at.desc()).all()


def get_asset(db: Session, asset_id: uuid.UUID) -> Asset | None:
    return (
        db.query(Asset)
        .options(
            joinedload(Asset.vehicle_meta),
            joinedload(Asset.created_by),
            joinedload(Asset.components),
            joinedload(Asset.service_records)
            .joinedload(ServiceRecord.components),
            joinedload(Asset.service_records)
            .joinedload(ServiceRecord.created_by),
            joinedload(Asset.maintenance_tasks)
            .joinedload(MaintenanceTask.components),
            joinedload(Asset.maintenance_tasks)
            .joinedload(MaintenanceTask.created_by),
            joinedload(Asset.maintenance_tasks)
            .joinedload(MaintenanceTask.last_completed_record),
        )
        .filter(Asset.id == asset_id)
        .first()
    )


def create_asset(db: Session, data: dict, user: User) -> Asset:
    vehicle_fields = _extract_vehicle_fields(data)
    filtered = _filter_allowed(data, ASSET_ALLOWED_FIELDS)
    asset = Asset(created_by_id=user.id, **filtered)
    if data.get("category") == "vehicle" and any(vehicle_fields.values()):
        asset.vehicle_meta = VehicleMeta(**vehicle_fields)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset(db: Session, asset: Asset, data: dict) -> Asset:
    vehicle_fields = _extract_vehicle_fields(data)
    filtered = _filter_allowed(data, ASSET_ALLOWED_FIELDS)
    for key, value in filtered.items():
        setattr(asset, key, value)

    if asset.category == "vehicle":
        if asset.vehicle_meta:
            for key, value in vehicle_fields.items():
                setattr(asset.vehicle_meta, key, value)
        elif any(vehicle_fields.values()):
            asset.vehicle_meta = VehicleMeta(**vehicle_fields)
    elif asset.vehicle_meta:
        db.delete(asset.vehicle_meta)

    db.commit()
    db.refresh(asset)
    return asset


def retire_asset(db: Session, asset: Asset, reason: str | None = None) -> Asset:
    asset.status = "retired"
    asset.retired_date = date.today()
    asset.retired_reason = reason
    db.commit()
    db.refresh(asset)
    return asset


def _validate_image_bytes(content: bytes, ext: str) -> bool:
    """Verify file content matches expected image format magic bytes."""
    if ext in (".jpg", ".jpeg"):
        return content[:3] == b"\xff\xd8\xff"
    elif ext == ".png":
        return content[:8] == b"\x89PNG\r\n\x1a\n"
    elif ext == ".gif":
        return content[:6] in (b"GIF87a", b"GIF89a")
    elif ext == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


async def save_photo(
    asset_id: uuid.UUID, file: UploadFile, upload_dir: str
) -> str:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"File type {file.content_type} not allowed")

    # Validate file extension
    original = os.path.basename(file.filename) if file.filename else ""
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension {ext!r} not allowed")

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) == 0:
        raise ValueError("File is empty")
    if len(content) > MAX_UPLOAD_SIZE:
        raise ValueError("File too large (max 10MB)")

    # Validate magic bytes match the extension
    if not _validate_image_bytes(content, ext):
        raise ValueError("File content does not match expected image format")

    # Generate random filename to prevent XSS via crafted extensions
    safe_filename = f"{uuid.uuid4().hex}{ext}"

    relative_dir = str(asset_id)
    asset_dir = _safe_upload_path(upload_dir, relative_dir)
    if not asset_dir:
        raise ValueError("Unsafe upload path")
    os.makedirs(asset_dir, exist_ok=True)

    relative_file_path = f"{relative_dir}/{safe_filename}"
    file_path = _safe_upload_path(upload_dir, relative_file_path)
    if not file_path:
        raise ValueError("Unsafe upload path")
    with open(file_path, "wb") as f:
        f.write(content)

    return relative_file_path


def _extract_vehicle_fields(data: dict) -> dict:
    """Pop vehicle-specific fields from data dict and return them."""
    fields = {}
    for key in ["vin", "license_plate", "current_mileage", "fuel_type", "insurance_info"]:
        if key in data:
            fields[key] = data.pop(key)
    return fields
