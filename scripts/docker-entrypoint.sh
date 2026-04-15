#!/bin/sh
set -eu

python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

database_url = os.environ["DATABASE_URL"]
deadline = time.time() + int(os.environ.get("DATABASE_WAIT_SECONDS", "60"))
last_error = None

while time.time() < deadline:
    try:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        sys.exit(0)
    except Exception as exc:
        last_error = exc
        time.sleep(2)

print(f"database was not ready before timeout: {last_error}", file=sys.stderr)
sys.exit(1)
PY

alembic upgrade head

exec "$@"
