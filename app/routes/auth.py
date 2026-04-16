from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    MFA_PENDING_COOKIE_NAME,
    create_pending_mfa_cookie,
    create_session_cookie,
    load_pending_mfa_cookie,
    verify_session_cookie,
)
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.auth import (
    authenticate_user,
    clear_failed_logins,
    login_is_rate_limited,
    record_failed_login,
    update_last_login,
)
from app.services.mfa import (
    clear_failed_mfa,
    mfa_is_rate_limited,
    record_failed_mfa,
    verify_user_mfa_code,
)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    settings = get_settings()
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and verify_session_cookie(cookie, settings.secret_key, settings.session_max_age):
        return RedirectResponse("/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "login.html", {"error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"

    if login_is_rate_limited(
        username,
        client_host,
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    ):
        return request.app.state.templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=429,
        )

    user = authenticate_user(db, username, password)
    if not user:
        record_failed_login(username, client_host)
        return request.app.state.templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or password"}, status_code=401
        )

    clear_failed_logins(username, client_host)
    if getattr(user, "totp_enabled", False):
        pending_cookie = create_pending_mfa_cookie(
            user.id,
            settings.secret_key,
            user.session_version,
        )
        response = RedirectResponse("/login/totp", status_code=303)
        response.set_cookie(
            MFA_PENDING_COOKIE_NAME,
            pending_cookie,
            max_age=300,
            httponly=True,
            secure=settings.effective_cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    update_last_login(db, user)
    cookie = create_session_cookie(user.id, settings.secret_key, user.session_version)
    response = RedirectResponse("/", status_code=303)
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


def _pending_mfa_user(request: Request, db: Session) -> User | None:
    settings = get_settings()
    pending_cookie = request.cookies.get(MFA_PENDING_COOKIE_NAME)
    if not pending_cookie:
        return None
    pending = load_pending_mfa_cookie(pending_cookie, settings.secret_key)
    if not pending:
        return None
    user = db.get(User, pending["user_id"])
    if (
        not user
        or not user.is_active
        or not getattr(user, "totp_enabled", False)
        or user.session_version != pending["session_version"]
    ):
        return None
    return user


@router.get("/login/totp", response_class=HTMLResponse)
def login_totp_page(request: Request, db: Session = Depends(get_db)):
    user = _pending_mfa_user(request, db)
    if not user:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(MFA_PENDING_COOKIE_NAME, path="/")
        return response
    return request.app.state.templates.TemplateResponse(
        request,
        "login_totp.html",
        {"error": None, "username": user.username},
    )


@router.post("/login/totp", response_class=HTMLResponse)
async def login_totp_submit(request: Request, db: Session = Depends(get_db)):
    user = _pending_mfa_user(request, db)
    if not user:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(MFA_PENDING_COOKIE_NAME, path="/")
        return response

    form = await request.form()
    code = form.get("code", "")
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    rate_limit_id = str(user.id)

    if mfa_is_rate_limited(
        rate_limit_id,
        client_host,
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    ):
        return request.app.state.templates.TemplateResponse(
            request,
            "login_totp.html",
            {"error": "Invalid two-factor code", "username": user.username},
            status_code=429,
        )

    if not verify_user_mfa_code(db, user, code):
        record_failed_mfa(rate_limit_id, client_host)
        return request.app.state.templates.TemplateResponse(
            request,
            "login_totp.html",
            {"error": "Invalid two-factor code", "username": user.username},
            status_code=401,
        )

    clear_failed_mfa(rate_limit_id, client_host)
    update_last_login(db, user)
    cookie = create_session_cookie(user.id, settings.secret_key, user.session_version)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        cookie,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        MFA_PENDING_COOKIE_NAME,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    settings = get_settings()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        MFA_PENDING_COOKIE_NAME,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
