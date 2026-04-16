import uuid
from secrets import token_urlsafe

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.datastructures import MutableHeaders
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.database import get_session_factory
from app.logging_config import bind_user_id
from app.models.user import User

COOKIE_NAME = "homebase_session"
MFA_PENDING_COOKIE_NAME = "homebase_pending_mfa"
CSRF_COOKIE_NAME = "homebase_csrf"
EXEMPT_PREFIXES = ("/login", "/health", "/ready", "/static", "/favicon.ico")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_SALT = "homebase-csrf"
MFA_PENDING_SALT = "homebase-pending-mfa"
MFA_PENDING_MAX_AGE = 300
MAX_CSRF_FORM_BODY_SIZE = 12 * 1024 * 1024


def create_session_cookie(user_id: uuid.UUID, secret_key: str, session_version: int = 0) -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps({"user_id": str(user_id), "session_version": session_version})


def create_pending_mfa_cookie(
    user_id: uuid.UUID,
    secret_key: str,
    session_version: int = 0,
) -> str:
    serializer = URLSafeTimedSerializer(secret_key, salt=MFA_PENDING_SALT)
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


def load_pending_mfa_cookie(cookie: str, secret_key: str) -> dict | None:
    serializer = URLSafeTimedSerializer(secret_key, salt=MFA_PENDING_SALT)
    try:
        data = serializer.loads(cookie, max_age=MFA_PENDING_MAX_AGE)
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


class RequestBodyTooLarge(Exception):
    pass


async def read_request_body(receive: Receive, max_size: int) -> bytes:
    chunks = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        chunks.append(chunk)
        size += len(chunk)
        if size > max_size:
            raise RequestBodyTooLarge
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def csrf_cookie_headers(token: str, settings) -> list[tuple[bytes, bytes]]:
    response = Response()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=settings.session_max_age,
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return list(response.raw_headers)


def with_csrf_cookie(send: Send, token: str, settings) -> Send:
    raw_headers = csrf_cookie_headers(token, settings)

    async def send_with_cookie(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            for name, value in raw_headers:
                headers.append(name.decode("latin-1"), value.decode("latin-1"))
        await send(message)

    return send_with_cookie


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})
        request = Request(scope, receive)
        path = request.url.path
        settings = get_settings()
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_cookie_valid = verify_csrf_token(
            csrf_cookie, settings.secret_key, settings.session_max_age
        )
        request.state.csrf_token = (
            csrf_cookie if csrf_cookie_valid else create_csrf_token(settings.secret_key)
        )

        receive_for_app = receive

        if settings.effective_csrf_enabled and request.method in MUTATING_METHODS:
            submitted_token = request.headers.get("x-csrf-token")
            if not submitted_token:
                try:
                    body = await read_request_body(receive, MAX_CSRF_FORM_BODY_SIZE)
                except RequestBodyTooLarge:
                    response = HTMLResponse("Request body too large", status_code=413)
                    await response(scope, receive, send)
                    return
                receive_for_app = replay_receive(body)
                form_request = Request(scope, replay_receive(body))
                try:
                    form = await form_request.form()
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
                response = HTMLResponse("CSRF validation failed", status_code=403)
                await response(scope, receive_for_app, send)
                return

        if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            if not csrf_cookie_valid:
                send = with_csrf_cookie(send, request.state.csrf_token, settings)
            await self.app(scope, receive_for_app, send)
            return

        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            response = RedirectResponse("/login", status_code=303)
            await response(scope, receive_for_app, send)
            return

        session_data = load_session_cookie(cookie, settings.secret_key, settings.session_max_age)
        if not session_data:
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            await response(scope, receive_for_app, send)
            return

        # Use app.state.get_user_by_id if set (for test overrides), else default
        lookup = getattr(request.app.state, "get_user_by_id", default_get_user_by_id)
        user = lookup(session_data["user_id"])

        if not user or not getattr(user, "is_active", True):
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            await response(scope, receive_for_app, send)
            return
        if getattr(user, "session_version", 0) != session_data["session_version"]:
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE_NAME)
            await response(scope, receive_for_app, send)
            return

        request.state.user = user
        bind_user_id(user.id)
        if not csrf_cookie_valid:
            send = with_csrf_cookie(send, request.state.csrf_token, settings)
        await self.app(scope, receive_for_app, send)


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
