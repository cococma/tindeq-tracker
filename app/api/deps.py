"""Shared FastAPI dependencies."""

from app.db import get_db_connection


def db():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()
