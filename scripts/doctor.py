from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OK = "ok"
WARN = "warn"
FAIL = "fail"
DEFAULT_SECRET = "dev-secret-key-change-in-production"
DEFAULT_ADMIN_PASSWORD = "changeme"
VALID_LOG_FORMATS = {"plain", "json"}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
REQUIRED_IMPORTS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "psycopg2": "psycopg2",
    "alembic": "alembic",
    "jinja2": "jinja2",
    "python-multipart": "multipart",
    "pydantic-settings": "pydantic_settings",
    "bcrypt": "bcrypt",
    "itsdangerous": "itsdangerous",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    details: str | None = None
    next_step: str | None = None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    results = run_checks(PROJECT_ROOT, verbose=args.verbose)
    if args.json:
        print(json.dumps(results_payload(results), indent=2))
    else:
        print_human(results, verbose=args.verbose)
    return 1 if aggregate_status(results) == FAIL else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose a local HomeBase environment.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--verbose", action="store_true", help="Show extra diagnostic details.")
    return parser.parse_args(argv)


def run_checks(root: Path, *, verbose: bool = False) -> list[CheckResult]:
    settings_result, settings = check_settings(root)
    results = [
        check_python_version(sys.version_info),
        check_repo_root(root),
        check_virtualenv(root),
        check_dependencies(),
        check_env_file(root),
        settings_result,
    ]
    if settings:
        results.extend(
            [
                check_production_defaults(settings),
                check_logging_config(settings),
                check_upload_dir(settings, root),
                check_email_config(settings),
                check_prod_deployment_files(root),
                check_database(settings.database_url, "database"),
                check_schema(settings.database_url),
                check_database(test_database_url(settings.database_url), "test database"),
            ]
        )
    return results


def check_python_version(version_info) -> CheckResult:
    version = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    if (version_info.major, version_info.minor) >= (3, 12):
        return CheckResult("python", OK, f"Python {version}")
    return CheckResult(
        "python",
        FAIL,
        f"Python {version} is too old",
        next_step="Install Python 3.12 or newer.",
    )


def check_repo_root(root: Path) -> CheckResult:
    expected = ("pyproject.toml", "alembic.ini", ".env.example")
    missing = [name for name in expected if not (root / name).exists()]
    if not missing:
        return CheckResult("repo", OK, "Repository root looks correct")
    return CheckResult(
        "repo",
        FAIL,
        f"Missing expected file(s): {', '.join(missing)}",
        details=str(root),
        next_step="Run this command from the HomeBase repository checkout.",
    )


def check_virtualenv(root: Path) -> CheckResult:
    if (root / "venv").exists():
        return CheckResult("venv", OK, "Local venv exists")
    return CheckResult(
        "venv",
        WARN,
        "Local venv was not found",
        next_step="Create one with `python -m venv venv`.",
    )


def check_env_file(root: Path) -> CheckResult:
    if (root / ".env").exists():
        return CheckResult("env", OK, ".env exists")
    return CheckResult(
        "env",
        FAIL,
        ".env is missing",
        next_step="Copy `.env.example` to `.env` and fill in local values.",
    )


def check_dependencies() -> CheckResult:
    missing = []
    for package_name, import_name in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(package_name)
    if not missing:
        return CheckResult("dependencies", OK, "Required Python packages import")
    return CheckResult(
        "dependencies",
        FAIL,
        f"Missing Python package(s): {', '.join(missing)}",
        next_step="Activate the venv and run `pip install -r requirements-dev.txt`.",
    )


def check_settings(root: Path) -> tuple[CheckResult, object | None]:
    try:
        from app.config import Settings

        settings = Settings(_env_file=root / ".env")
    except Exception as exc:
        return (
            CheckResult(
                "settings",
                FAIL,
                "App settings could not be loaded",
                details=str(exc),
                next_step="Fix invalid values in `.env`.",
            ),
            None,
        )
    return CheckResult("settings", OK, "App settings load"), settings


def check_production_defaults(settings) -> CheckResult:
    if not settings.is_production:
        return CheckResult("production-safety", OK, "Production safety checks are not required")

    problems = []
    parsed_base_url = urlparse(settings.base_url)
    if settings.secret_key == DEFAULT_SECRET:
        problems.append("SECRET_KEY is still the default")
    if settings.admin_password == DEFAULT_ADMIN_PASSWORD:
        problems.append("ADMIN_PASSWORD is still the default")
    if parsed_base_url.scheme != "https" or not parsed_base_url.hostname:
        problems.append("BASE_URL must be an https:// URL")
    if not settings.effective_allowed_hosts:
        problems.append("ALLOWED_HOSTS must include at least one host")
    if not settings.effective_cookie_secure:
        problems.append("secure cookies are disabled")
    if not settings.effective_csrf_enabled:
        problems.append("CSRF protection is disabled")

    if not problems:
        return CheckResult("production-safety", OK, "Production safety settings look safe")
    return CheckResult(
        "production-safety",
        FAIL,
        "; ".join(problems),
        next_step="Update production `.env` before deploying.",
    )


def check_logging_config(settings) -> CheckResult:
    problems = []
    if settings.log_level.upper() not in VALID_LOG_LEVELS:
        problems.append("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    if settings.log_format not in VALID_LOG_FORMATS:
        problems.append("LOG_FORMAT must be plain or json")

    if not problems:
        return CheckResult("logging", OK, "Logging config is valid")
    return CheckResult("logging", FAIL, "; ".join(problems))


def check_upload_dir(settings, root: Path) -> CheckResult:
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.is_absolute():
        upload_dir = root / upload_dir

    if upload_dir.exists():
        if os.access(upload_dir, os.W_OK):
            return CheckResult(
                "uploads",
                OK,
                "Upload directory is writable",
                details=str(upload_dir),
            )
        return CheckResult(
            "uploads",
            FAIL,
            "Upload directory exists but is not writable",
            details=str(upload_dir),
        )

    parent = upload_dir.parent
    if parent.exists() and os.access(parent, os.W_OK):
        return CheckResult(
            "uploads",
            OK,
            "Upload directory can be created",
            details=str(upload_dir),
        )
    return CheckResult(
        "uploads",
        FAIL,
        "Upload directory parent is not writable",
        details=str(upload_dir),
        next_step="Create the upload directory or choose a writable UPLOAD_DIR.",
    )


def check_email_config(settings) -> CheckResult:
    if not settings.email_enabled:
        return CheckResult("email", WARN, "Email delivery is disabled")
    if settings.resend_api_key and settings.email_from:
        return CheckResult("email", OK, "Email delivery is configured")
    return CheckResult(
        "email",
        FAIL,
        "Email delivery is enabled but configuration is incomplete",
        next_step="Set EMAIL_FROM and RESEND_API_KEY, or disable EMAIL_ENABLED.",
    )


def check_prod_deployment_files(root: Path) -> CheckResult:
    paths = {
        "compose": root / "compose.prod.yaml",
        "env": root / ".env.prod.example",
        "caddy": root / "deploy" / "caddy" / "Caddyfile",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        return CheckResult(
            "prod-deploy",
            FAIL,
            f"Missing production deployment file(s): {', '.join(missing)}",
        )

    compose = paths["compose"].read_text(encoding="utf-8")
    env = paths["env"].read_text(encoding="utf-8")
    caddy = paths["caddy"].read_text(encoding="utf-8")
    problems = []
    app_block = _compose_service_block(compose, "app")
    if "ports:" in app_block:
        problems.append("app service must not publish host ports in compose.prod.yaml")
    if "app:8000" not in caddy:
        problems.append("Caddyfile must reverse proxy to app:8000")
    for required in (
        "HOMEBASE_DOMAIN=",
        "BASE_URL=https://",
        "ENVIRONMENT=production",
        "DEBUG=false",
        "COOKIE_SECURE=true",
        "CSRF_ENABLED=true",
        "LOG_FORMAT=json",
    ):
        if required not in env:
            problems.append(f".env.prod.example missing {required}")

    if problems:
        return CheckResult("prod-deploy", FAIL, "; ".join(problems))
    return CheckResult("prod-deploy", OK, "Production deployment templates look safe")


def _compose_service_block(compose: str, service_name: str) -> str:
    marker = f"  {service_name}:"
    lines = compose.splitlines()
    try:
        start = lines.index(marker)
    except ValueError:
        return ""
    block = []
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        block.append(line)
    return "\n".join(block)


def check_database(database_url: str, name: str) -> CheckResult:
    from sqlalchemy import text

    return _with_database_connection(
        database_url,
        name,
        lambda connection: connection.execute(text("SELECT 1")),
    )


def check_schema(database_url: str) -> CheckResult:
    from app.services.schema_guard import assert_database_schema_current

    def validate(connection):
        assert_database_schema_current(connection)

    result = _with_database_connection(database_url, "schema", validate)
    if result.status == OK:
        return CheckResult("schema", OK, "Database schema is current")
    return result


def test_database_url(database_url: str) -> str:
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        return configured
    try:
        from sqlalchemy.engine import make_url

        url = make_url(database_url)
        database = url.database or ""
        if database.endswith("_test"):
            return database_url
        return url.set(database="homebase_test").render_as_string(hide_password=False)
    except Exception:
        return database_url


def redact_url(database_url: str) -> str:
    try:
        from sqlalchemy.engine import make_url

        url = make_url(database_url)
    except Exception:
        return "<invalid database url>"
    if url.password is None:
        return str(url)
    return url.set(password="<redacted>").render_as_string(hide_password=False)


def aggregate_status(results: Iterable[CheckResult]) -> str:
    statuses = [result.status for result in results]
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return OK


def results_payload(results: list[CheckResult]) -> dict:
    return {
        "status": aggregate_status(results),
        "checks": [asdict(result) for result in results],
    }


def print_human(results: list[CheckResult], *, verbose: bool = False) -> None:
    for result in results:
        print(f"[{result.status}] {result.message}")
        if result.next_step:
            print(f"[next] {result.next_step}")
        if verbose and result.details:
            print(f"[detail] {result.details}")
    print(f"\nOverall status: {aggregate_status(results)}")


def _with_database_connection(
    database_url: str,
    name: str,
    callback: Callable,
) -> CheckResult:
    safe_url = redact_url(database_url)
    try:
        from sqlalchemy import create_engine

        engine = create_engine(database_url)
        with engine.connect() as connection:
            callback(connection)
    except Exception as exc:
        if exc.__class__.__name__ == "SchemaVersionError":
            return CheckResult(name, FAIL, str(exc), details=safe_url)
        return CheckResult(
            name,
            FAIL,
            f"{name.title()} is not reachable",
            details=f"{safe_url}: {exc}",
            next_step="Check DATABASE_URL and PostgreSQL setup.",
        )
    finally:
        if "engine" in locals():
            engine.dispose()
    return CheckResult(name, OK, f"{name.title()} is reachable", details=safe_url)


if __name__ == "__main__":
    raise SystemExit(main())
