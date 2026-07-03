"""Lightweight SQL migration runner.

Usage: python -m app.migrate

Applies app/migrations/NNN_name.sql files in order, tracking progress in
schema_migrations. Each migration runs in its own transaction.
"""

import os
import re
import sys

from app.db import get_db_connection

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def _discover_migrations():
    files = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        m = re.match(r"^(\d+)_.+\.sql$", name)
        if m:
            files.append((int(m.group(1)), name))
    return files


def run():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    INTEGER PRIMARY KEY,
                    name       TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        pending = [(v, n) for v, n in _discover_migrations() if v not in applied]
        if not pending:
            print("Database is up to date.")
            return

        for version, name in pending:
            path = os.path.join(MIGRATIONS_DIR, name)
            with open(path) as f:
                sql = f.read()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (version, name),
                )
            conn.commit()
            print(f"Applied {name}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
