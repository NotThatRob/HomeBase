from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, create_session_cookie, verify_session_cookie
from app.config import get_settings
from app.database import get_db
from app.services.auth import (
    authenticate_user,
    clear_failed_logins,
    login_is_rate_limited,
    record_failed_login,
    update_last_login,
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
    return response
