"""Data access for Tindeq sessions, measurements, and baseline tests."""

from psycopg2.extras import RealDictCursor


def create_session(conn, cfg):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (
                exercise_type, grip_type, edge_depth_mm, target_weight_kg,
                on_seconds, off_seconds, target_reps, target_sets, set_rest_s,
                target_duration_s, target_pull_reps, hand, notes
            ) VALUES (
                %(exercise_type)s, %(grip_type)s, %(edge_depth_mm)s, %(target_weight_kg)s,
                %(on_seconds)s, %(off_seconds)s, %(target_reps)s, %(target_sets)s, %(set_rest_s)s,
                %(target_duration_s)s, %(target_pull_reps)s, %(hand)s, %(notes)s
            ) RETURNING id
            """,
            cfg,
        )
        session_id = cur.fetchone()[0]
    conn.commit()
    return session_id


def close_session(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET ended_at = NOW() WHERE id = %s", (session_id,))
    conn.commit()


def delete_session(conn, session_id):
    """Delete a session; its measurements go with it (ON DELETE CASCADE)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        deleted = cur.rowcount
    conn.commit()
    return deleted


def save_baseline(conn, cfg, peak_force_kg, rfd_kg_per_s=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO baseline_tests (
                test_type, grip_type, edge_depth_mm,
                peak_force_kg, rfd_kg_per_s, peak_force_rfd_kg, hand, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cfg["exercise_type"],
                cfg["grip_type"],
                cfg["edge_depth_mm"],
                peak_force_kg,
                rfd_kg_per_s,
                peak_force_kg if rfd_kg_per_s else None,
                cfg.get("hand", "right"),
                cfg.get("notes"),
            ),
        )
    conn.commit()


def insert_measurements_batch(conn, session_id, samples):
    """Insert a batch of (force_kg, device_ts_us) tuples."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO measurements (session_id, recorded_at, force_kg, device_ts_us)
            VALUES (%s, NOW(), %s, %s)
            """,
            [(session_id, force, ts) for force, ts in samples],
        )
    conn.commit()


# ── Reads ─────────────────────────────────────────────────────────────────────

def list_sessions(conn, limit=None):
    """Sessions newest-first with per-session sample count and peak force."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT s.*,
                   COUNT(m.id)                  AS n_samples,
                   COALESCE(MAX(m.force_kg), 0) AS peak_force_kg
            FROM sessions s
            LEFT JOIN measurements m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def get_session(conn, session_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT s.*,
                   COUNT(m.id)                  AS n_samples,
                   COALESCE(MAX(m.force_kg), 0) AS peak_force_kg,
                   COALESCE(AVG(m.force_kg), 0) AS mean_force_kg
            FROM sessions s
            LEFT JOIN measurements m ON m.session_id = s.id
            WHERE s.id = %s
            GROUP BY s.id
            """,
            (session_id,),
        )
        return cur.fetchone()


def get_session_trace(conn, session_id, max_points=4000):
    """Force trace downsampled via per-bucket min/max so peaks survive.

    Returns (t_seconds, force_kg) lists with t relative to the first sample.
    """
    buckets = max(1, max_points // 2)
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH t AS (
                SELECT id, force_kg, device_ts_us,
                       NTILE(%s) OVER (ORDER BY id) AS bucket
                FROM measurements
                WHERE session_id = %s
            ),
            ranked AS (
                SELECT id, force_kg, device_ts_us,
                       ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY force_kg DESC, id) AS rmax,
                       ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY force_kg ASC,  id) AS rmin
                FROM t
            )
            SELECT force_kg, device_ts_us
            FROM ranked
            WHERE rmax = 1 OR rmin = 1
            ORDER BY id
            """,
            (buckets, session_id),
        )
        rows = cur.fetchall()
    if not rows:
        return [], []
    t0 = rows[0][1] or 0
    ts = [round(((r[1] or 0) - t0) / 1_000_000, 3) for r in rows]
    force = [round(r[0], 3) for r in rows]
    return ts, force


def list_baselines(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM baseline_tests ORDER BY tested_at")
        return cur.fetchall()


def session_peaks_by_grip(conn):
    """Per-session peak force over time, for the trends page."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT s.id, s.started_at, s.exercise_type, s.grip_type, s.hand,
                   MAX(m.force_kg) AS peak_force_kg
            FROM sessions s
            JOIN measurements m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.started_at
            """
        )
        return cur.fetchall()


def dashboard_stats(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM sessions)                                          AS total_sessions,
                (SELECT COUNT(*) FROM sessions
                  WHERE started_at >= date_trunc('week', NOW()))                          AS sessions_this_week,
                (SELECT MAX(force_kg) FROM measurements)                                  AS all_time_peak_kg,
                (SELECT MAX(m.force_kg) FROM measurements m
                  JOIN sessions s ON s.id = m.session_id
                  WHERE s.started_at >= date_trunc('week', NOW()))                        AS peak_this_week_kg,
                (SELECT MAX(started_at) FROM sessions)                                    AS last_session_at
            """
        )
        return cur.fetchone()
