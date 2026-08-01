"""Data access for the training calendar: planned items and training blocks."""

from psycopg2.extras import RealDictCursor


# ── Planned items ─────────────────────────────────────────────────────────────

def list_items(conn, start, end):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM planned_items WHERE plan_date BETWEEN %s AND %s ORDER BY plan_date, id",
            (start, end),
        )
        return cur.fetchall()


def get_item(conn, item_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM planned_items WHERE id = %s", (item_id,))
        return cur.fetchone()


def create_item(conn, item, source="user"):
    """item: dict(plan_date, item_type, title, details)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO planned_items (plan_date, item_type, title, details, source)
            VALUES (%(plan_date)s, %(item_type)s, %(title)s, %(details)s, %(source)s)
            RETURNING id
            """,
            {**item, "source": source},
        )
        item_id = cur.fetchone()[0]
    conn.commit()
    return item_id


def update_item(conn, item_id, item):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE planned_items
            SET plan_date = %(plan_date)s, item_type = %(item_type)s,
                title = %(title)s, details = %(details)s, updated_at = NOW()
            WHERE id = %(id)s
            """,
            {**item, "id": item_id},
        )
        updated = cur.rowcount
    conn.commit()
    return updated


def delete_item(conn, item_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM planned_items WHERE id = %s", (item_id,))
        deleted = cur.rowcount
    conn.commit()
    return deleted


# ── Training blocks ───────────────────────────────────────────────────────────

def list_blocks(conn, start=None, end=None):
    """All blocks, or those overlapping [start, end]."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if start and end:
            cur.execute(
                "SELECT * FROM training_blocks WHERE start_date <= %s AND end_date >= %s ORDER BY start_date, id",
                (end, start),
            )
        else:
            cur.execute("SELECT * FROM training_blocks ORDER BY start_date, id")
        return cur.fetchall()


def get_block(conn, block_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM training_blocks WHERE id = %s", (block_id,))
        return cur.fetchone()


def create_block(conn, block):
    """block: dict(name, start_date, end_date, focus)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO training_blocks (name, start_date, end_date, focus)
            VALUES (%(name)s, %(start_date)s, %(end_date)s, %(focus)s)
            RETURNING id
            """,
            block,
        )
        block_id = cur.fetchone()[0]
    conn.commit()
    return block_id


def update_block(conn, block_id, block):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE training_blocks
            SET name = %(name)s, start_date = %(start_date)s, end_date = %(end_date)s,
                focus = %(focus)s, updated_at = NOW()
            WHERE id = %(id)s
            """,
            {**block, "id": block_id},
        )
        updated = cur.rowcount
    conn.commit()
    return updated


def delete_block(conn, block_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM training_blocks WHERE id = %s", (block_id,))
        deleted = cur.rowcount
    conn.commit()
    return deleted


def apply_proposal(conn, item_ops, block_ops):
    """Apply a validated coach proposal in one transaction.

    item_ops / block_ops: lists of (action, payload) tuples. Created rows get
    source='coach'. Commits once — all-or-nothing.
    """
    counts = {"items": 0, "blocks": 0}
    with conn.cursor() as cur:
        for action, p in item_ops:
            if action == "add":
                cur.execute(
                    """
                    INSERT INTO planned_items (plan_date, item_type, title, details, source)
                    VALUES (%(plan_date)s, %(item_type)s, %(title)s, %(details)s, 'coach')
                    """,
                    p,
                )
            elif action == "update":
                cur.execute(
                    """
                    UPDATE planned_items
                    SET plan_date = %(plan_date)s, item_type = %(item_type)s,
                        title = %(title)s, details = %(details)s, updated_at = NOW()
                    WHERE id = %(id)s
                    """,
                    p,
                )
            else:
                cur.execute("DELETE FROM planned_items WHERE id = %(id)s", p)
            counts["items"] += 1
        for action, p in block_ops:
            if action == "add":
                cur.execute(
                    """
                    INSERT INTO training_blocks (name, start_date, end_date, focus)
                    VALUES (%(name)s, %(start_date)s, %(end_date)s, %(focus)s)
                    """,
                    p,
                )
            elif action == "update":
                cur.execute(
                    """
                    UPDATE training_blocks
                    SET name = %(name)s, start_date = %(start_date)s, end_date = %(end_date)s,
                        focus = %(focus)s, updated_at = NOW()
                    WHERE id = %(id)s
                    """,
                    p,
                )
            else:
                cur.execute("DELETE FROM training_blocks WHERE id = %(id)s", p)
            counts["blocks"] += 1
    conn.commit()
    return counts


# ── Calendar reads over existing data ─────────────────────────────────────────

def month_facts(conn, start, end):
    """Per-day markers of what actually happened, for the calendar grid.

    Returns {date: {"hangboard": n, "entry_types": [..], "checkin": bool, "weight": bool}}.
    """
    facts = {}

    def day(d):
        return facts.setdefault(d, {"hangboard": 0, "entry_types": [], "checkin": False, "weight": False})

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT started_at::date AS d, COUNT(*) AS n FROM sessions WHERE started_at::date BETWEEN %s AND %s GROUP BY 1",
            (start, end),
        )
        for r in cur.fetchall():
            day(r["d"])["hangboard"] = r["n"]

        cur.execute(
            "SELECT entry_date AS d, entry_type FROM journal_entries WHERE entry_date BETWEEN %s AND %s ORDER BY id",
            (start, end),
        )
        for r in cur.fetchall():
            day(r["d"])["entry_types"].append(r["entry_type"])

        cur.execute(
            "SELECT log_date AS d FROM wellness_logs WHERE log_date BETWEEN %s AND %s",
            (start, end),
        )
        for r in cur.fetchall():
            day(r["d"])["checkin"] = True

        cur.execute(
            """
            SELECT DISTINCT recorded_at::date AS d FROM body_metrics
            WHERE metric = 'weight_kg' AND recorded_at::date BETWEEN %s AND %s
            """,
            (start, end),
        )
        for r in cur.fetchall():
            day(r["d"])["weight"] = True

    return facts


def day_detail(conn, d):
    """Everything recorded on one day: hangboard sessions, journal entries,
    wellness, weight — plus that day's planned items."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT s.*,
                   COUNT(m.id)                  AS n_samples,
                   COALESCE(MAX(m.force_kg), 0) AS peak_force_kg
            FROM sessions s
            LEFT JOIN measurements m ON m.session_id = s.id
            WHERE s.started_at::date = %s
            GROUP BY s.id
            ORDER BY s.started_at
            """,
            (d,),
        )
        hangboard = cur.fetchall()

        cur.execute(
            """
            SELECT e.*,
                   row_to_json(cs.*) AS climbing,
                   row_to_json(w.*)  AS workout
            FROM journal_entries e
            LEFT JOIN climbing_sessions cs ON cs.journal_entry_id = e.id
            LEFT JOIN workouts w           ON w.journal_entry_id = e.id
            WHERE e.entry_date = %s
            ORDER BY e.id
            """,
            (d,),
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

        cur.execute("SELECT * FROM wellness_logs WHERE log_date = %s", (d,))
        wellness = cur.fetchone()

        cur.execute(
            """
            SELECT value FROM body_metrics
            WHERE metric = 'weight_kg' AND recorded_at::date = %s
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (d,),
        )
        row = cur.fetchone()
        weight = row["value"] if row else None

    return {
        "hangboard": hangboard,
        "entries": entries,
        "wellness": wellness,
        "weight": weight,
        "planned": list_items(conn, d, d),
    }
