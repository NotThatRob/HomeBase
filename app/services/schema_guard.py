from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SchemaVersionError(RuntimeError):
    """Raised when the database schema is not at the Alembic head."""


def assert_database_schema_current(connection: Connection) -> None:
    expected_heads = _expected_heads()
    current_heads = tuple(MigrationContext.configure(connection).get_current_heads())
    validate_schema_heads(current_heads, expected_heads)


def validate_schema_heads(
    current_heads: tuple[str, ...],
    expected_heads: tuple[str, ...],
) -> None:
    if len(expected_heads) != 1:
        raise SchemaVersionError(
            "Alembic is configured with multiple heads. Resolve migration branches "
            "before starting HomeBase."
        )

    if current_heads != expected_heads:
        current = ", ".join(current_heads) if current_heads else "none"
        expected = expected_heads[0]
        raise SchemaVersionError(
            "Database schema is not current. "
            f"Current revision: {current}. Expected head: {expected}. "
            "Run `alembic upgrade head` before starting HomeBase."
        )


def _expected_heads() -> tuple[str, ...]:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return tuple(script.get_heads())
