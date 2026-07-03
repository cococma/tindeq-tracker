"""Data access for Tindeq sessions, measurements, and baseline tests."""


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
