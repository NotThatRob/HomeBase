import base64
import io
import re
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta

import bcrypt
import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User

ISSUER_NAME = "HomeBase"
SETUP_EXPIRES_MINUTES = 15
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

_mfa_attempts: dict[str, deque[datetime]] = defaultdict(deque)


class MfaError(ValueError):
    pass


def validate_totp_encryption_key(key: str) -> None:
    try:
        Fernet(key.encode())
    except Exception as exc:
        raise ValueError("TOTP_ENCRYPTION_KEY must be a valid Fernet key") from exc


def generate_totp_encryption_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    settings = get_settings()
    validate_totp_encryption_key(settings.effective_totp_encryption_key)
    return Fernet(settings.effective_totp_encryption_key.encode())


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(encrypted_secret: str | None) -> str | None:
    if not encrypted_secret:
        return None
    try:
        return _fernet().decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as exc:
        raise MfaError("Stored two-factor secret could not be decrypted.") from exc


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=f"{ISSUER_NAME}:{username}",
        issuer_name=ISSUER_NAME,
    )


def qr_code_data_uri(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def begin_totp_setup(db: Session, user: User) -> tuple[str, str]:
    secret = generate_secret()
    user.totp_pending_secret_encrypted = encrypt_secret(secret)
    user.totp_pending_created_at = datetime.now()
    db.commit()
    db.refresh(user)
    return secret, qr_code_data_uri(provisioning_uri(secret, user.username))


def pending_secret(user: User) -> str | None:
    if not user.totp_pending_secret_encrypted or not user.totp_pending_created_at:
        return None
    if datetime.now() - user.totp_pending_created_at > timedelta(minutes=SETUP_EXPIRES_MINUTES):
        return None
    return decrypt_secret(user.totp_pending_secret_encrypted)


def verify_totp_code(secret: str | None, code: str) -> bool:
    normalized = normalize_totp_code(code)
    if not secret or not normalized:
        return False
    return pyotp.TOTP(secret).verify(normalized, valid_window=1)


def normalize_totp_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "")


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    codes = set()
    while len(codes) < count:
        codes.add(generate_recovery_code())
    return sorted(codes)


def hash_recovery_code(code: str) -> str:
    normalized = normalize_recovery_code(code)
    return bcrypt.hashpw(normalized.encode(), bcrypt.gensalt()).decode()


def recovery_code_entries(codes: list[str]) -> list[dict]:
    return [
        {
            "hash": hash_recovery_code(code),
            "used_at": None,
        }
        for code in codes
    ]


def remaining_recovery_code_count(user: User) -> int:
    return len([entry for entry in user.recovery_codes or [] if not entry.get("used_at")])


def consume_recovery_code(user: User, code: str) -> bool:
    normalized = normalize_recovery_code(code)
    if not normalized:
        return False
    entries = [dict(entry) for entry in user.recovery_codes or []]
    for entry in entries:
        if entry.get("used_at"):
            continue
        hashed = entry.get("hash")
        if hashed and bcrypt.checkpw(normalized.encode(), hashed.encode()):
            entry["used_at"] = datetime.now().isoformat()
            user.recovery_codes = entries
            return True
    return False


def confirm_totp_setup(db: Session, user: User, code: str) -> list[str] | None:
    secret = pending_secret(user)
    if not verify_totp_code(secret, code):
        return None
    recovery_codes = generate_recovery_codes()
    user.totp_secret_encrypted = encrypt_secret(secret or "")
    user.totp_pending_secret_encrypted = None
    user.totp_pending_created_at = None
    user.totp_enabled = True
    user.totp_enabled_at = datetime.now()
    user.recovery_codes = recovery_code_entries(recovery_codes)
    user.session_version += 1
    db.commit()
    db.refresh(user)
    return recovery_codes


def verify_user_mfa_code(db: Session, user: User, code: str) -> bool:
    secret = decrypt_secret(user.totp_secret_encrypted)
    if verify_totp_code(secret, code):
        return True
    if consume_recovery_code(user, code):
        db.commit()
        db.refresh(user)
        return True
    return False


def disable_totp(db: Session, user: User) -> None:
    user.totp_secret_encrypted = None
    user.totp_pending_secret_encrypted = None
    user.totp_pending_created_at = None
    user.totp_enabled = False
    user.totp_enabled_at = None
    user.recovery_codes = None
    user.session_version += 1
    db.commit()
    db.refresh(user)


def regenerate_recovery_codes(db: Session, user: User) -> list[str]:
    recovery_codes = generate_recovery_codes()
    user.recovery_codes = recovery_code_entries(recovery_codes)
    user.session_version += 1
    db.commit()
    db.refresh(user)
    return recovery_codes


def mfa_is_rate_limited(
    identifier: str,
    client_host: str,
    max_attempts: int,
    window_seconds: int,
) -> bool:
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    attempts = _mfa_attempts[_rate_limit_key(identifier, client_host)]
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= max_attempts


def record_failed_mfa(identifier: str, client_host: str) -> None:
    _mfa_attempts[_rate_limit_key(identifier, client_host)].append(datetime.now())


def clear_failed_mfa(identifier: str, client_host: str) -> None:
    _mfa_attempts.pop(_rate_limit_key(identifier, client_host), None)


def _rate_limit_key(identifier: str, client_host: str) -> str:
    return f"{client_host}:{identifier.strip().lower()}"
