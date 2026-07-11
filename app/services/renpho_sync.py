"""Renpho sync orchestration: cloud API → body_metrics, with cursor + status."""

from datetime import datetime, timedelta, timezone

from app import config
from app.db import get_db_connection
from app.repos import metrics as repo
from app.services.renpho_client import (
    FIELD_TO_METRIC,
    RenphoClient,
    RenphoError,
    measurement_timestamp,
)

SOURCE = "renpho"
AUTO_SYNC_STALENESS = timedelta(hours=12)


def credentials_configured() -> bool:
    return bool(config.RENPHO_EMAIL and config.RENPHO_PASSWORD)


def _rows_from_measurement(m: dict):
    ts = measurement_timestamp(m)
    if not ts:
        return
    recorded_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    for field, metric in FIELD_TO_METRIC.items():
        value = m.get(field)
        if value in (None, 0, ""):  # Renpho pads absent impedance metrics with 0
            continue
        yield {
            "source": SOURCE,
            "metric": metric,
            "value": float(value),
            "recorded_at": recorded_at,
            "metadata": None,
        }


def sync(conn=None) -> dict:
    """Pull new measurements since the stored cursor. Returns a status dict."""
    own_conn = conn is None
    if own_conn:
        conn = get_db_connection()
    try:
        if not credentials_configured():
            status = "RENPHO_EMAIL / RENPHO_PASSWORD not configured"
            repo.set_sync_state(conn, SOURCE, status)
            return {"ok": False, "status": status}

        # The Renpho Health API has no incremental cursor — fetch everything;
        # insert_metrics is idempotent (unique on source/metric/recorded_at).
        client = RenphoClient(config.RENPHO_EMAIL, config.RENPHO_PASSWORD)
        try:
            measurements = client.measurements()
        finally:
            client.close()

        rows = [r for m in measurements for r in _rows_from_measurement(m)]
        inserted = repo.insert_metrics(conn, rows) if rows else 0
        max_ts = max((measurement_timestamp(m) or 0 for m in measurements), default=0)
        status = f"ok · {len(measurements)} measurements · {inserted} new values"
        repo.set_sync_state(conn, SOURCE, status, cursor_data={"last_at": max_ts}, synced=True)
        return {"ok": True, "status": status, "inserted": inserted}
    except RenphoError as e:
        repo.set_sync_state(conn, SOURCE, f"error: {e}")
        return {"ok": False, "status": str(e)}
    except Exception as e:
        repo.set_sync_state(conn, SOURCE, f"error: {type(e).__name__}: {e}")
        return {"ok": False, "status": f"{type(e).__name__}: {e}"}
    finally:
        if own_conn:
            conn.close()


def sync_if_stale() -> bool:
    """Opportunistic startup sync. Returns True if a sync was attempted."""
    if not credentials_configured():
        return False
    conn = get_db_connection()
    try:
        state = repo.get_sync_state(conn, SOURCE)
        if state and state["last_synced_at"]:
            age = datetime.now(timezone.utc) - state["last_synced_at"]
            if age < AUTO_SYNC_STALENESS:
                return False
        sync(conn)
        return True
    finally:
        conn.close()
