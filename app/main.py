import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import AuthMiddleware, csrf_token
from app.config import get_settings
from app.database import get_session_factory
from app.logging_config import (
    REQUEST_ID_HEADER,
    bind_request_context,
    bind_user_id,
    clear_request_context,
    monotonic_ms,
    request_id_from_header,
    setup_logging,
)
from app.models.user import User
from app.routes.assets import router as assets_router
from app.routes.auth import router as auth_router
from app.routes.components import router as components_router
from app.routes.documents import router as documents_router
from app.routes.fuel_logs import quick_router as fuel_logs_quick_router
from app.routes.fuel_logs import router as fuel_logs_router
from app.routes.maintenance_tasks import router as maintenance_tasks_router
from app.routes.pages import router as pages_router
from app.routes.recurring_costs import router as recurring_costs_router
from app.routes.reports import router as reports_router
from app.routes.search import router as search_router
from app.routes.service_records import router as service_records_router
from app.routes.settings import router as settings_router
from app.routes.wizard import router as wizard_router
from app.services.schema_guard import assert_database_schema_current
from app.template_filters import compact_date, currency, file_size, long_date, short_date

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("homebase.access")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Refuse to start with default secrets in production
    is_production = settings.environment == "production" or not settings.debug
    if is_production:
        if settings.debug:
            raise RuntimeError("DEBUG must be false in production.")
        if settings.secret_key == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "SECRET_KEY must be changed before running in production. "
                "Set the SECRET_KEY environment variable."
            )
        if settings.admin_password == "changeme":
            raise RuntimeError(
                "ADMIN_PASSWORD must be changed before running in production. "
                "Set the ADMIN_PASSWORD environment variable."
            )
        parsed_base_url = urlparse(settings.base_url)
        if parsed_base_url.scheme != "https" or not parsed_base_url.hostname:
            raise RuntimeError("BASE_URL must be an https:// URL in production.")
        if not settings.effective_allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must include at least one host in production.")
        if not settings.effective_cookie_secure:
            raise RuntimeError("Secure cookies must be enabled in production.")
        if not settings.effective_csrf_enabled:
            raise RuntimeError("CSRF protection must be enabled in production.")

    # Seed admin user if no users exist
    session = get_session_factory()()
    try:
        assert_database_schema_current(session.connection())
        user_count = session.query(func.count(User.id)).scalar()
        if user_count == 0:
            admin = User(
                username=settings.admin_username,
                display_name="Admin",
                email=f"{settings.admin_username}@homebase.local",
                role="admin",
                password_hash="",
            )
            admin.set_password(settings.admin_password)
            session.add(admin)
            session.commit()
            logger.warning(
                "Created admin user '%s' with default password. Change it immediately.",
                settings.admin_username,
            )
    finally:
        session.close()

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    app = FastAPI(
        title="HomeBase",
        version="0.2.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.state.templates.env.globals["csrf_token"] = csrf_token
    app.state.templates.env.filters["compact_date"] = compact_date
    app.state.templates.env.filters["currency"] = currency
    app.state.templates.env.filters["file_size"] = file_size
    app.state.templates.env.filters["long_date"] = long_date
    app.state.templates.env.filters["short_date"] = short_date
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.effective_allowed_hosts)

    # Auth middleware
    app.add_middleware(AuthMiddleware)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "img-src 'self' data:; "
            "frame-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        return response

    @app.middleware("http")
    async def request_logging(request, call_next):
        request_id = bind_request_context(
            request_id_from_header(request.headers.get(REQUEST_ID_HEADER))
        )
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception(
                "Unhandled request exception",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client_host": request.client.host if request.client else "unknown",
                },
            )
            response = PlainTextResponse("Internal Server Error", status_code=500)
        user = getattr(request.state, "user", None)
        user_id = getattr(user, "id", None)
        bind_user_id(user_id)
        response.headers[REQUEST_ID_HEADER] = request_id
        access_logger.info(
            "HTTP request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": monotonic_ms(start),
                "client_host": request.client.host if request.client else "unknown",
            },
        )
        clear_request_context()
        return response

    # Routers
    app.include_router(auth_router)
    app.include_router(assets_router)
    app.include_router(components_router)
    app.include_router(service_records_router)
    app.include_router(recurring_costs_router)
    app.include_router(fuel_logs_quick_router)
    app.include_router(fuel_logs_router)
    app.include_router(maintenance_tasks_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(reports_router)
    app.include_router(settings_router)
    app.include_router(wizard_router)
    app.include_router(pages_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/ready")
    def ready():
        session = get_session_factory()()
        try:
            connection = session.connection()
            connection.execute(text("SELECT 1"))
            assert_database_schema_current(connection)
        finally:
            session.close()
        return {"status": "ready", "version": "0.2.0"}

    return app


app = create_app()
