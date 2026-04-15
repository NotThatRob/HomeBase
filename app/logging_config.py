import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from app.config import Settings

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_old_factory = logging.getLogRecordFactory()
_factory_configured = False


class PlainFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s [%(name)s] "
            "request_id=%(request_id)s user_id=%(user_id)s %(message)s"
        )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": record.request_id,
            "user_id": record.user_id,
        }
        for key in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_host",
            "frequency",
            "dry_run",
            "due_now",
            "digest_time",
            "processed",
            "sent",
            "skipped",
            "failed",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def setup_logging(settings: Settings) -> None:
    _configure_record_factory()
    log_level = _log_level(settings.log_level)
    formatter = JsonFormatter() if settings.log_format == "json" else PlainFormatter()

    root = logging.getLogger()
    root.setLevel(log_level)
    handler = _homebase_handler(root)
    handler.setFormatter(formatter)
    handler.setLevel(log_level)

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.log_sql else logging.WARNING
    )


def bind_request_context(request_id: str | None = None) -> str:
    value = request_id or str(uuid.uuid4())
    _request_id.set(value)
    _user_id.set(None)
    return value


def bind_user_id(user_id: object | None) -> None:
    _user_id.set(str(user_id) if user_id else None)


def clear_request_context() -> None:
    _request_id.set(None)
    _user_id.set(None)


def current_request_id() -> str | None:
    return _request_id.get()


def request_id_from_header(value: str | None) -> str:
    value = (value or "").strip()
    return value[:128] if value else str(uuid.uuid4())


def monotonic_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _configure_record_factory() -> None:
    global _factory_configured
    if _factory_configured:
        return

    def record_factory(*args, **kwargs):
        record = _old_factory(*args, **kwargs)
        record.request_id = _request_id.get() or "-"
        record.user_id = _user_id.get() or "-"
        return record

    logging.setLogRecordFactory(record_factory)
    _factory_configured = True


def _homebase_handler(root: logging.Logger) -> logging.Handler:
    for handler in root.handlers:
        if getattr(handler, "_homebase_handler", False):
            return handler
    handler = logging.StreamHandler(sys.stderr)
    handler._homebase_handler = True
    root.addHandler(handler)
    return handler


def _log_level(value: str) -> int:
    return getattr(logging, value.upper(), logging.INFO)
