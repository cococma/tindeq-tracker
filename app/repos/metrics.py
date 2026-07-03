"""Data access for body metrics and sync state."""

import json

from psycopg2.extras import RealDictCursor


def insert_metrics(conn, rows):
    """Insert (source, metric, value, recorded_at, metadata) rows idempotently.

    Returns the number of rows actually inserted (conflicts skipped).
    """
    inserted = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO body_metrics (source, metric, value, recorded_at, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source, metric, recorded_at) DO NOTHING
                """,
                (
                    r["source"], r["metric"], r["value"], r["recorded_at"],
                    json.dumps(r["metadata"]) if r.get("metadata") else None,
                ),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def metric_series(conn, metric):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT recorded_at, value, source
            FROM body_metrics
            WHERE metric = %s
            ORDER BY recorded_at
            """,
            (metric,),
        )
        return cur.fetchall()


def available_metrics(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT metric, COUNT(*) AS n, MAX(recorded_at) AS latest
            FROM body_metrics
            GROUP BY metric
            ORDER BY metric
            """
        )
        return cur.fetchall()


def latest_metrics(conn):
    """Most recent value per metric."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (metric) metric, value, recorded_at
            FROM body_metrics
            ORDER BY metric, recorded_at DESC
            """
        )
        return {r["metric"]: r for r in cur.fetchall()}


def get_sync_state(conn, source):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM sync_state WHERE source = %s", (source,))
        return cur.fetchone()


def set_sync_state(conn, source, status, cursor_data=None, synced=False):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_state (source, last_synced_at, last_status, cursor)
            VALUES (%s, CASE WHEN %s THEN NOW() END, %s, %s)
            ON CONFLICT (source) DO UPDATE SET
                last_synced_at = CASE WHEN %s THEN NOW() ELSE sync_state.last_synced_at END,
                last_status = EXCLUDED.last_status,
                cursor = COALESCE(EXCLUDED.cursor, sync_state.cursor)
            """,
            (source, synced, status, json.dumps(cursor_data) if cursor_data else None, synced),
        )
    conn.commit()
