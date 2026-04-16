import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, create_session_cookie, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.auth import (
    active_admin_count,
    change_password,
    create_user,
    get_user_by_email,
    get_user_by_username,
    list_users,
    reset_user_password,
    set_user_active,
    update_notification_preferences,
    update_profile,
    update_user_admin,
)
from app.services.email_reminders import send_digest_for_user
from app.services.mfa import (
    begin_totp_setup,
    clear_failed_mfa,
    confirm_totp_setup,
    disable_totp,
    mfa_is_rate_limited,
    pending_secret,
    provisioning_uri,
    qr_code_data_uri,
    record_failed_mfa,
    regenerate_recovery_codes,
    remaining_recovery_code_count,
    verify_user_mfa_code,
)

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)


def _settings_context(user, **overrides) -> dict:
    context = {
        "user": user,
        "users": [],
        "profile_error": None,
        "profile_success": None,
        "password_error": None,
        "password_success": None,
        "notification_error": None,
        "notification_success": None,
        "admin_error": None,
        "admin_success": None,
        "digest_test_error": None,
        "digest_test_success": None,
        "security_error": None,
        "security_success": None,
        "recovery_code_count": remaining_recovery_code_count(user),
        "roles": ["user", "admin"],
        "digest_frequencies": ["daily", "weekly"],
        "email_configured": get_settings().email_configured,
    }
    context.update(overrides)
    return context


def _render_settings(
    request: Request,
    user,
    db: Session | None = None,
    **context,
) -> HTMLResponse:
    if user.role == "admin" and db and "users" not in context:
        context["users"] = list_users(db)
    return request.app.state.templates.TemplateResponse(
        request,
        "settings.html",
        _settings_context(user, **context),
    )


def _require_admin(user) -> HTMLResponse | None:
    if user.role != "admin":
        return HTMLResponse("Access denied", status_code=403)
    return None


def _target_user_or_error(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def _current_settings_user(request: Request, db: Session) -> User:
    request_user = get_current_user(request)
    return db.get(User, request_user.id) or request_user


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _mfa_rate_limited(request: Request, user: User) -> bool:
    settings = get_settings()
    return mfa_is_rate_limited(
        str(user.id),
        _client_host(request),
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    )


def _record_failed_settings_mfa(request: Request, user: User) -> None:
    record_failed_mfa(str(user.id), _client_host(request))


def _clear_failed_settings_mfa(request: Request, user: User) -> None:
    clear_failed_mfa(str(user.id), _client_host(request))


def _set_session_cookie(response, user: User) -> None:
    settings = get_settings()
    cookie = create_session_cookie(user.id, settings.secret_key, user.session_version)
    response.set_cookie(
        COOKIE_NAME,
        cookie,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    return _render_settings(request, user, db)


@router.post("/security/totp/setup", response_class=HTMLResponse)
def settings_totp_setup_start(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    if user.totp_enabled:
        return _render_settings(
            request,
            user,
            db,
            security_error="Two-factor authentication is already on.",
        )
    secret, qr_data_uri = begin_totp_setup(db, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/totp_setup.html",
        {
            "user": user,
            "secret": secret,
            "qr_data_uri": qr_data_uri,
            "error": None,
        },
    )


@router.get("/security/totp/setup", response_class=HTMLResponse)
def settings_totp_setup_page(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    secret = pending_secret(user)
    if user.totp_enabled or not secret:
        return RedirectResponse("/settings", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "settings/totp_setup.html",
        {
            "user": user,
            "secret": secret,
            "qr_data_uri": qr_code_data_uri(provisioning_uri(secret, user.username)),
            "error": None,
        },
    )


@router.post("/security/totp/confirm", response_class=HTMLResponse)
async def settings_totp_setup_confirm(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    form = await request.form()
    code = form.get("code", "")
    secret = pending_secret(user)
    if not secret:
        return _render_settings(
            request,
            user,
            db,
            security_error="Two-factor setup expired. Start again when you are ready.",
        )
    if _mfa_rate_limited(request, user):
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/totp_setup.html",
            {
                "user": user,
                "secret": secret,
                "qr_data_uri": qr_code_data_uri(provisioning_uri(secret, user.username)),
                "error": "Too many attempts. Wait a few minutes before trying again.",
            },
            status_code=429,
        )

    recovery_codes = confirm_totp_setup(db, user, code)
    if not recovery_codes:
        _record_failed_settings_mfa(request, user)
        return request.app.state.templates.TemplateResponse(
            request,
            "settings/totp_setup.html",
            {
                "user": user,
                "secret": secret,
                "qr_data_uri": qr_code_data_uri(provisioning_uri(secret, user.username)),
                "error": "That code did not work. Check your authenticator app and try again.",
            },
            status_code=400,
        )
    _clear_failed_settings_mfa(request, user)
    response = request.app.state.templates.TemplateResponse(
        request,
        "settings/totp_recovery_codes.html",
        {"user": user, "recovery_codes": recovery_codes, "regenerated": False},
    )
    _set_session_cookie(response, user)
    return response


@router.post("/security/totp/disable", response_class=HTMLResponse)
async def settings_totp_disable(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    if not user.totp_enabled:
        return _render_settings(
            request,
            user,
            db,
            security_error="Two-factor authentication is already off.",
        )
    form = await request.form()
    code = form.get("code", "")
    if _mfa_rate_limited(request, user):
        return _render_settings(
            request,
            user,
            db,
            security_error="Too many attempts. Wait a few minutes before trying again.",
        )
    if not verify_user_mfa_code(db, user, code):
        _record_failed_settings_mfa(request, user)
        return _render_settings(
            request,
            user,
            db,
            security_error="Enter a current authenticator code or recovery code to turn this off.",
        )
    _clear_failed_settings_mfa(request, user)
    disable_totp(db, user)
    response = _render_settings(
        request,
        user,
        db,
        security_success="Two-factor authentication is off.",
    )
    _set_session_cookie(response, user)
    return response


@router.post("/security/totp/recovery-codes", response_class=HTMLResponse)
async def settings_totp_recovery_codes(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    if not user.totp_enabled:
        return _render_settings(
            request,
            user,
            db,
            security_error="Turn on two-factor authentication before creating recovery codes.",
        )
    form = await request.form()
    code = form.get("code", "")
    if _mfa_rate_limited(request, user):
        return _render_settings(
            request,
            user,
            db,
            security_error="Too many attempts. Wait a few minutes before trying again.",
        )
    if not verify_user_mfa_code(db, user, code):
        _record_failed_settings_mfa(request, user)
        return _render_settings(
            request,
            user,
            db,
            security_error="Enter a current authenticator code or recovery code to make new codes.",
        )
    _clear_failed_settings_mfa(request, user)
    recovery_codes = regenerate_recovery_codes(db, user)
    response = request.app.state.templates.TemplateResponse(
        request,
        "settings/totp_recovery_codes.html",
        {"user": user, "recovery_codes": recovery_codes, "regenerated": True},
    )
    _set_session_cookie(response, user)
    return response


@router.post("/profile", response_class=HTMLResponse)
async def settings_profile_update(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    form = await request.form()
    display_name = form.get("display_name", "").strip()
    email = form.get("email", "").strip().lower()

    if not display_name or not email:
        return _render_settings(
            request,
            user,
            db,
            profile_error="Display name and email are required.",
        )

    existing_email = get_user_by_email(db, email)
    if existing_email and existing_email.id != user.id:
        return _render_settings(
            request,
            user,
            db,
            profile_error="That email is already in use.",
        )

    update_profile(db, user, display_name, email)
    return _render_settings(
        request,
        user,
        db,
        profile_success="Profile updated.",
    )


@router.post("/notifications", response_class=HTMLResponse)
async def settings_notifications_update(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    form = await request.form()
    enabled = "email_digest_enabled" in form
    frequency = form.get("email_digest_frequency", "daily").strip()
    digest_time = form.get("email_digest_time", "08:00").strip()

    try:
        update_notification_preferences(
            db,
            user,
            enabled=enabled,
            frequency=frequency,
            digest_time=digest_time,
        )
    except ValueError as exc:
        return _render_settings(request, user, db, notification_error=str(exc))

    return _render_settings(
        request,
        user,
        db,
        notification_success="Notification preferences updated.",
    )


@router.post("/digest-test", response_class=HTMLResponse)
def settings_send_test_digest(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    if not user.email:
        return _render_settings(
            request,
            user,
            db,
            digest_test_error="Add an email to your profile before sending a test digest.",
        )

    result = send_digest_for_user(db, user, settings=get_settings())
    if result.status == "sent":
        return _render_settings(
            request,
            user,
            db,
            digest_test_success=f"Digest sent to {result.email} ({result.task_count} task(s)).",
        )
    if result.status == "skipped":
        return _render_settings(
            request,
            user,
            db,
            digest_test_error=f"Digest not sent: {result.detail}.",
        )
    return _render_settings(
        request,
        user,
        db,
        digest_test_error=f"Digest failed: {result.detail}.",
    )


@router.post("/password", response_class=HTMLResponse)
async def settings_password_update(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    form = await request.form()
    current_password = form.get("current_password", "")
    new_password = form.get("new_password", "")
    confirm_password = form.get("confirm_password", "")

    if not user.verify_password(current_password):
        return _render_settings(
            request,
            user,
            db,
            password_error="Current password is incorrect.",
        )
    if len(new_password) < 8:
        return _render_settings(
            request,
            user,
            db,
            password_error="New password must be at least 8 characters.",
        )
    if new_password != confirm_password:
        return _render_settings(
            request,
            user,
            db,
            password_error="New passwords do not match.",
        )

    change_password(db, user, new_password)
    settings = get_settings()
    cookie = create_session_cookie(user.id, settings.secret_key, user.session_version)
    response = RedirectResponse("/settings?password_changed=1", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        cookie,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/users", response_class=HTMLResponse)
async def settings_user_create(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    denied = _require_admin(user)
    if denied:
        return denied

    form = await request.form()
    username = form.get("username", "").strip().lower()
    display_name = form.get("display_name", "").strip()
    email = form.get("email", "").strip().lower()
    role = form.get("role", "user").strip()
    password = form.get("password", "")

    if not username or not display_name or not email or not password:
        return _render_settings(
            request,
            user,
            db,
            admin_error="Username, display name, email, and password are required.",
        )
    if role not in {"user", "admin"}:
        return _render_settings(request, user, db, admin_error="Invalid role.")
    if len(password) < 8:
        return _render_settings(
            request,
            user,
            db,
            admin_error="Temporary password must be at least 8 characters.",
        )
    if get_user_by_username(db, username):
        return _render_settings(
            request,
            user,
            db,
            admin_error="That username is already in use.",
        )
    if get_user_by_email(db, email):
        return _render_settings(
            request,
            user,
            db,
            admin_error="That email is already in use.",
        )

    created = create_user(
        db,
        username=username,
        display_name=display_name,
        email=email,
        role=role,
        password=password,
    )
    return _render_settings(
        request,
        user,
        db,
        admin_success=f"Created user {created.username}.",
    )


@router.post("/users/{user_id}/edit", response_class=HTMLResponse)
async def settings_user_edit(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    denied = _require_admin(user)
    if denied:
        return denied

    target = _target_user_or_error(db, user_id)
    if not target:
        return _render_settings(request, user, db, admin_error="User not found.")

    form = await request.form()
    display_name = form.get("display_name", "").strip()
    email = form.get("email", "").strip().lower()
    role = form.get("role", "user").strip()

    if not display_name or not email:
        return _render_settings(
            request,
            user,
            db,
            admin_error="Display name and email are required.",
        )
    if role not in {"user", "admin"}:
        return _render_settings(request, user, db, admin_error="Invalid role.")
    if target.id == user.id and role != user.role:
        return _render_settings(
            request,
            user,
            db,
            admin_error="You cannot change your own role.",
        )
    if (
        target.role == "admin"
        and role != "admin"
        and target.is_active
        and active_admin_count(db) <= 1
    ):
        return _render_settings(
            request,
            user,
            db,
            admin_error="At least one active admin is required.",
        )

    existing_email = get_user_by_email(db, email)
    if existing_email and existing_email.id != target.id:
        return _render_settings(
            request,
            user,
            db,
            admin_error="That email is already in use.",
        )

    update_user_admin(db, target, display_name=display_name, email=email, role=role)
    logger.info(
        "Admin user updated",
        extra={"admin_user_id": str(user.id), "target_user_id": str(target.id)},
    )
    return _render_settings(
        request,
        user,
        db,
        admin_success=f"Updated user {target.username}.",
    )


@router.post("/users/{user_id}/password", response_class=HTMLResponse)
async def settings_user_password_reset(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    denied = _require_admin(user)
    if denied:
        return denied

    target = _target_user_or_error(db, user_id)
    if not target:
        return _render_settings(request, user, db, admin_error="User not found.")

    form = await request.form()
    password = form.get("password", "")
    if len(password) < 8:
        return _render_settings(
            request,
            user,
            db,
            admin_error="Temporary password must be at least 8 characters.",
        )

    reset_user_password(db, target, password)
    logger.info(
        "Admin reset user password",
        extra={"admin_user_id": str(user.id), "target_user_id": str(target.id)},
    )
    return _render_settings(
        request,
        user,
        db,
        admin_success=f"Reset password for {target.username}.",
    )


@router.post("/users/{user_id}/status", response_class=HTMLResponse)
async def settings_user_status_update(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    denied = _require_admin(user)
    if denied:
        return denied

    target = _target_user_or_error(db, user_id)
    if not target:
        return _render_settings(request, user, db, admin_error="User not found.")
    if target.id == user.id:
        return _render_settings(
            request,
            user,
            db,
            admin_error="You cannot change your own account status.",
        )

    form = await request.form()
    action = form.get("action", "").strip()
    if action not in {"disable", "reactivate"}:
        return _render_settings(request, user, db, admin_error="Invalid status action.")

    is_active = action == "reactivate"
    if not is_active and target.role == "admin" and active_admin_count(db) <= 1:
        return _render_settings(
            request,
            user,
            db,
            admin_error="At least one active admin is required.",
        )

    set_user_active(db, target, is_active=is_active)
    status = "reactivated" if is_active else "disabled"
    logger.info(
        "Admin changed user status",
        extra={
            "admin_user_id": str(user.id),
            "target_user_id": str(target.id),
            "target_is_active": is_active,
        },
    )
    return _render_settings(
        request,
        user,
        db,
        admin_success=f"{target.username} {status}.",
    )


@router.post("/users/{user_id}/totp/disable", response_class=HTMLResponse)
async def settings_user_totp_disable(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _current_settings_user(request, db)
    denied = _require_admin(user)
    if denied:
        return denied

    target = _target_user_or_error(db, user_id)
    if not target:
        return _render_settings(request, user, db, admin_error="User not found.")
    if target.id == user.id:
        return _render_settings(
            request,
            user,
            db,
            admin_error="Use your Security settings to change your own two-factor setup.",
        )
    if not target.totp_enabled:
        return _render_settings(
            request,
            user,
            db,
            admin_error=f"{target.username} does not have two-factor authentication on.",
        )

    form = await request.form()
    admin_password = form.get("admin_password", "")
    admin_mfa_code = form.get("admin_mfa_code", "")
    if not user.verify_password(admin_password):
        return _render_settings(
            request,
            user,
            db,
            admin_error=(
                "Your password is required to turn off another user's "
                "two-factor authentication."
            ),
        )
    if user.totp_enabled:
        if _mfa_rate_limited(request, user):
            return _render_settings(
                request,
                user,
                db,
                admin_error="Too many attempts. Wait a few minutes before trying again.",
            )
        if not verify_user_mfa_code(db, user, admin_mfa_code):
            _record_failed_settings_mfa(request, user)
            return _render_settings(
                request,
                user,
                db,
                admin_error="Enter your current two-factor code before changing another user.",
            )
        _clear_failed_settings_mfa(request, user)

    disable_totp(db, target)
    logger.warning(
        "Admin disabled user two-factor authentication",
        extra={"admin_user_id": str(user.id), "target_user_id": str(target.id)},
    )
    return _render_settings(
        request,
        user,
        db,
        admin_success=f"Turned off two-factor authentication for {target.username}.",
    )
