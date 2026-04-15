import uuid
from secrets import token_urlsafe

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.database import get_session_factory
from app.logging_config import bind_user_id
from app.models.user import User

COOKIE_NAME = "homebase_session"
CSRF_COOKIE_NAME = "homebase_csrf"
EXEMPT_PREFIXES = ("/login", "/health", "/ready", "/static", "/favicon.ico")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_SALT = "homebase-csrf"


def create_session_cookie(user_id: uuid.UUID, secret_key: str, session_version: int = 0) -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps({"user_id": str(user_id), "session_version": session_version})


def load_session_cookie(cookie: str, secret_key: str, max_age: int) -> dict | None:
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        data = serializer.loads(cookie, max_age=max_age)
        return {
            "user_id": uuid.UUID(data["user_id"]),
            "session_version": int(data.get("session_version", 0)),
        }
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def verify_session_cookie(
    cookie: str, secret_key: str, max_age: int
) -> uuid.UUID | None:
    data = load_session_cookie(cookie, secret_key, max_age)
    return data["user_id"] if data else None


def create_csrf_token(secret_key: str) -> str:
    serializer = URLSafeTimedSerializer(secret_key, salt=CSRF_SALT)
    return serializer.dumps({"nonce": token_urlsafe(32)})


def verify_csrf_token(token: str | None, secret_key: str, max_age: int) -> bool:
    if not token:
        return False
    serializer = URLSafeTimedSerializer(secret_key, salt=CSRF_SALT)
    try:
        data = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("nonce"))


def csrf_token(request: Request) -> str:
    return getattr(request.state, "csrf_token", "")


def default_get_user_by_id(user_id: uuid.UUID) -> User | None:
    """Look up user from a fresh DB session. Used in production."""
    session = get_session_factory()()
    try:
        return session.get(User, user_id)
    finally:
        session.close()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        settings = get_settings()
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_cookie_valid = verify_csrf_token(
            csrf_cookie, settings.secret_key, settings.session_max_age
        )
        request.state.csrf_token = (
            csrf_cookie if csrf_cookie_valid else create_csrf_token(settings.secret_key)
        )

        if settings.effective_csrf_enabled and request.method in MUTATING_METHODS:
            submitted_token = request.headers.get("x-csrf-token")
            if not submitted_token:
                try:
                    form = await request.form()
                except Exception:
                    form = {}
                submitted_token = form.get("csrf_token")
            if (
                not csrf_cookie_valid
                or submitted_token != csrf_cookie
                or not verify_csrf_token(
                    submitted_token,
                    settings.secret_key,
                    settings.session_max_age,
                )
            ):
                return HTMLResponse("CSRF validation failed", status_code=403)

        if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            response = await call_next(request)
            if not csrf_cookie_valid:
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    request.state.csrf_token,
                    max_age=settings.session_max_age,
                    secure=settings.effective_cookie_secure,
                    httponly=True,
                    samesite="lax",
                    path="/",
                )
            return response

        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return RedirectResponse("/login", status_code=303)

        session_data = load_session_cookie(cookie, settings.secret_key, settings.session_max_age)
        if not session_data:
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            return response

        # Use app.state.get_user_by_id if set (for test overrides), else default
        lookup = getattr(request.app.state, "get_user_by_id", default_get_user_by_id)
        user = lookup(session_data["user_id"])

        if not user or not getattr(user, "is_active", True):
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            return response
        if getattr(user, "session_version", 0) != session_data["session_version"]:
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            return response

        request.state.user = user
        bind_user_id(user.id)
        response = await call_next(request)
        if not csrf_cookie_valid:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                request.state.csrf_token,
                max_age=settings.session_max_age,
                secure=settings.effective_cookie_secure,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response


def get_current_user(request: Request) -> User:
    return request.state.user


def check_asset_access(asset, user: User, require_owner: bool = False) -> None:
    """Enforce visibility and ownership rules.

    Personal assets: only creator can view or edit.
    Shared assets: anyone can view; only creator or admin can edit/delete.
    """
    if asset.visibility == "personal" and asset.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if require_owner and asset.created_by_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
