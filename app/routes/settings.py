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


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = _current_settings_user(request, db)
    return _render_settings(request, user, db)


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
