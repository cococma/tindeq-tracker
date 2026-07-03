"""Data access for journal entries, climbing sessions, workouts, wellness."""

import json

from psycopg2.extras import RealDictCursor

from app.services.grades import parse_grade


# ── Entries ───────────────────────────────────────────────────────────────────

def list_entries(conn, limit=None):
    """Entries newest-first with their satellite rows attached."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT e.*,
                   row_to_json(cs.*) AS climbing,
                   row_to_json(w.*)  AS workout
            FROM journal_entries e
            LEFT JOIN climbing_sessions cs ON cs.journal_entry_id = e.id
            LEFT JOIN workouts w           ON w.journal_entry_id = e.id
            ORDER BY e.entry_date DESC, e.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        entries = cur.fetchall()

        climbing_ids = [e["climbing"]["id"] for e in entries if e["climbing"]]
        climbs_by_session = {}
        if climbing_ids:
            cur.execute(
                "SELECT * FROM climbs WHERE climbing_session_id = ANY(%s) ORDER BY grade_rank DESC NULLS LAST, id",
                (climbing_ids,),
            )
            for c in cur.fetchall():
                climbs_by_session.setdefault(c["climbing_session_id"], []).append(c)
        for e in entries:
            if e["climbing"]:
                e["climbs"] = climbs_by_session.get(e["climbing"]["id"], [])
    return entries


def get_entry(conn, entry_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT e.*,
                   row_to_json(cs.*) AS climbing,
                   row_to_json(w.*)  AS workout
            FROM journal_entries e
            LEFT JOIN climbing_sessions cs ON cs.journal_entry_id = e.id
            LEFT JOIN workouts w           ON w.journal_entry_id = e.id
            WHERE e.id = %s
            """,
            (entry_id,),
        )
        entry = cur.fetchone()
        if entry and entry["climbing"]:
            cur.execute(
                "SELECT * FROM climbs WHERE climbing_session_id = %s ORDER BY id",
                (entry["climbing"]["id"],),
            )
            entry["climbs"] = cur.fetchall()
    return entry


def create_entry(conn, entry, climbing=None, climbs=None, workout=None):
    """entry: dict(entry_date, entry_type, title, notes). Satellites optional."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO journal_entries (entry_date, entry_type, title, notes)
            VALUES (%(entry_date)s, %(entry_type)s, %(title)s, %(notes)s)
            RETURNING id
            """,
            entry,
        )
        entry_id = cur.fetchone()[0]
        if climbing is not None:
            _insert_climbing(cur, entry_id, climbing, climbs or [])
        if workout is not None:
            _insert_workout(cur, entry_id, workout)
    conn.commit()
    return entry_id


def update_entry(conn, entry_id, entry, climbing=None, climbs=None, workout=None):
    """Replace strategy: update the spine, delete + reinsert satellites."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE journal_entries
            SET entry_date = %(entry_date)s, entry_type = %(entry_type)s,
                title = %(title)s, notes = %(notes)s, updated_at = NOW()
            WHERE id = %(id)s
            """,
            {**entry, "id": entry_id},
        )
        cur.execute("DELETE FROM climbing_sessions WHERE journal_entry_id = %s", (entry_id,))
        cur.execute("DELETE FROM workouts WHERE journal_entry_id = %s", (entry_id,))
        if climbing is not None:
            _insert_climbing(cur, entry_id, climbing, climbs or [])
        if workout is not None:
            _insert_workout(cur, entry_id, workout)
    conn.commit()


def delete_entry(conn, entry_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM journal_entries WHERE id = %s", (entry_id,))
    conn.commit()


def _insert_climbing(cur, entry_id, climbing, climbs):
    cur.execute(
        """
        INSERT INTO climbing_sessions (
            journal_entry_id, location_type, location, discipline,
            duration_min, feel_rating, skin_rating, session_rpe
        ) VALUES (
            %(entry_id)s, %(location_type)s, %(location)s, %(discipline)s,
            %(duration_min)s, %(feel_rating)s, %(skin_rating)s, %(session_rpe)s
        ) RETURNING id
        """,
        {**climbing, "entry_id": entry_id},
    )
    cs_id = cur.fetchone()[0]
    for c in climbs:
        system, rank = parse_grade(c["grade"])
        cur.execute(
            """
            INSERT INTO climbs (
                climbing_session_id, name, grade, grade_system, grade_rank,
                style, attempts, sent, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cs_id, c.get("name"), c["grade"].strip(), system, rank,
                c.get("style"), c.get("attempts", 1),
                c.get("style") != "attempt", c.get("notes"),
            ),
        )


def _insert_workout(cur, entry_id, workout):
    cur.execute(
        """
        INSERT INTO workouts (journal_entry_id, workout_type, duration_min, session_rpe, details)
        VALUES (%(entry_id)s, %(workout_type)s, %(duration_min)s, %(session_rpe)s, %(details)s)
        """,
        {**workout, "entry_id": entry_id, "details": json.dumps(workout.get("details") or {})},
    )


# ── Wellness ──────────────────────────────────────────────────────────────────

def upsert_wellness(conn, log):
    """log: dict(log_date, sleep_hours, sleep_quality, soreness, fatigue, motivation, notes)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wellness_logs (log_date, sleep_hours, sleep_quality, soreness, fatigue, motivation, notes)
            VALUES (%(log_date)s, %(sleep_hours)s, %(sleep_quality)s, %(soreness)s, %(fatigue)s, %(motivation)s, %(notes)s)
            ON CONFLICT (log_date) DO UPDATE SET
                sleep_hours = EXCLUDED.sleep_hours,
                sleep_quality = EXCLUDED.sleep_quality,
                soreness = EXCLUDED.soreness,
                fatigue = EXCLUDED.fatigue,
                motivation = EXCLUDED.motivation,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            log,
        )
    conn.commit()


def get_wellness(conn, log_date):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM wellness_logs WHERE log_date = %s", (log_date,))
        return cur.fetchone()


def list_wellness(conn, days=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if days:
            cur.execute(
                "SELECT * FROM wellness_logs WHERE log_date >= CURRENT_DATE - %s ORDER BY log_date",
                (days,),
            )
        else:
            cur.execute("SELECT * FROM wellness_logs ORDER BY log_date")
        return cur.fetchall()


# ── Climbing analytics ────────────────────────────────────────────────────────

def climb_volume(conn):
    """All climbs with their session date, for volume-by-grade charts."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT e.entry_date, c.grade, c.grade_system, c.grade_rank, c.style,
                   c.attempts, c.sent, cs.location_type, cs.discipline
            FROM climbs c
            JOIN climbing_sessions cs ON cs.id = c.climbing_session_id
            JOIN journal_entries e    ON e.id = cs.journal_entry_id
            ORDER BY e.entry_date
            """
        )
        return cur.fetchall()
