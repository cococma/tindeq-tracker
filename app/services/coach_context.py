"""Assemble the training context the AI coach sees.

Everything is pre-aggregated SQL — raw 80 Hz force samples never reach the
prompt. Target ≤ ~6k tokens. Returns (markdown, snapshot_dict); the snapshot
is persisted with each recommendation for audit.
"""

from datetime import date, timedelta

from psycopg2.extras import RealDictCursor

from app.constants import GRIP_OPTIONS

GRIP_LABELS = dict(GRIP_OPTIONS)


def build_context(conn, days=28):
    blocks = []
    snapshot = {}

    for name, builder in [
        ("today", _today),
        ("profile", _profile),
        ("hangboard_recent", lambda c: _hangboard(c, days)),
        ("climbing_recent", lambda c: _climbing(c, days)),
        ("workouts_recent", lambda c: _workouts(c, days)),
        ("wellness", lambda c: _wellness(c, 14)),
        ("load_summary", _load_summary),
    ]:
        md, data = builder(conn)
        snapshot[name] = data
        if md:
            blocks.append(md)

    return "\n\n".join(blocks), snapshot


def _q(conn, sql, params=()):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ── Blocks ────────────────────────────────────────────────────────────────────

def _today(conn):
    today = date.today()
    md = f"## Today\n{today.strftime('%A, %B %d %Y')}"
    return md, {"date": today.isoformat(), "weekday": today.strftime("%A")}


def _profile(conn):
    lines = ["## Athlete profile"]
    data = {}

    weight = _q(conn, """
        SELECT ROUND(AVG(value)::numeric, 1) AS avg7
        FROM body_metrics
        WHERE metric = 'weight_kg' AND recorded_at >= NOW() - INTERVAL '7 days'
    """)
    trend = _q(conn, """
        SELECT ROUND(MIN(value)::numeric, 1) AS lo, ROUND(MAX(value)::numeric, 1) AS hi,
               (ARRAY_AGG(value ORDER BY recorded_at))[1]  AS first,
               (ARRAY_AGG(value ORDER BY recorded_at DESC))[1] AS last
        FROM body_metrics
        WHERE metric = 'weight_kg' AND recorded_at >= NOW() - INTERVAL '90 days'
    """)
    if weight and weight[0]["avg7"] is not None:
        lines.append(f"- Body weight: {weight[0]['avg7']} kg (7-day avg)")
        data["weight_kg_7d_avg"] = float(weight[0]["avg7"])
    if trend and trend[0]["first"] is not None:
        t = trend[0]
        lines.append(f"- Weight 90-day trend: {t['first']:.1f} → {t['last']:.1f} kg")
        data["weight_90d"] = {"first": t["first"], "last": t["last"]}

    bf = _q(conn, """
        SELECT ROUND(AVG(value)::numeric, 1) AS avg7 FROM body_metrics
        WHERE metric = 'body_fat_pct' AND recorded_at >= NOW() - INTERVAL '7 days'
    """)
    if bf and bf[0]["avg7"] is not None:
        lines.append(f"- Body fat: {bf[0]['avg7']}% (7-day avg)")
        data["body_fat_pct_7d_avg"] = float(bf[0]["avg7"])

    baselines = _q(conn, """
        SELECT DISTINCT ON (test_type, grip_type, hand)
               test_type, grip_type, hand, tested_at::date AS tested_on,
               peak_force_kg, rfd_kg_per_s
        FROM baseline_tests
        ORDER BY test_type, grip_type, hand, tested_at DESC
    """)
    best = {(b["test_type"], b["grip_type"], b["hand"]): b for b in _q(conn, """
        SELECT DISTINCT ON (test_type, grip_type, hand)
               test_type, grip_type, hand, peak_force_kg, rfd_kg_per_s
        FROM baseline_tests
        ORDER BY test_type, grip_type, hand,
                 COALESCE(peak_force_kg, 0) DESC, COALESCE(rfd_kg_per_s, 0) DESC
    """)}
    data["baselines"] = baselines
    for b in baselines:
        grip = GRIP_LABELS.get(b["grip_type"], b["grip_type"])
        key = (b["test_type"], b["grip_type"], b["hand"])
        if b["test_type"] == "mvc_test" and b["peak_force_kg"]:
            line = f"- MVC {grip} ({b['hand']}): {b['peak_force_kg']:.1f} kg on {b['tested_on']}"
            b_best = best.get(key)
            if b_best and b_best["peak_force_kg"] and b_best["peak_force_kg"] > b["peak_force_kg"]:
                line += f" (best ever {b_best['peak_force_kg']:.1f} kg)"
            lines.append(line)
        elif b["test_type"] == "rfd_test" and b["rfd_kg_per_s"]:
            lines.append(f"- RFD {grip} ({b['hand']}): {b['rfd_kg_per_s']:.1f} kg/s on {b['tested_on']}")

    if len(lines) == 1:
        lines.append("- No body metrics or baseline tests recorded yet.")
    return "\n".join(lines), data


def _hangboard(conn, days):
    rows = _q(conn, """
        SELECT s.id, s.started_at::date AS on_date, s.exercise_type, s.grip_type, s.hand,
               s.edge_depth_mm, s.target_weight_kg, s.on_seconds, s.off_seconds,
               s.target_sets, s.target_reps, s.notes,
               ROUND(MAX(m.force_kg)::numeric, 1) AS peak_kg,
               ROUND(AVG(m.force_kg) FILTER (WHERE m.force_kg > 1)::numeric, 1) AS working_mean_kg
        FROM sessions s
        LEFT JOIN measurements m ON m.session_id = s.id
        WHERE s.started_at >= NOW() - make_interval(days => %s)
        GROUP BY s.id
        ORDER BY s.started_at
    """, (days,))
    lines = [f"## Hangboard sessions (last {days} days)"]
    if not rows:
        lines.append("- None.")
    for r in rows:
        proto = ""
        if r["on_seconds"]:
            proto = f", {r['on_seconds']}/{r['off_seconds']}s × {r['target_sets']}x{r['target_reps']}"
        line = (f"- {r['on_date']}: {r['exercise_type']} — {r['grip_type']}, {r['hand']} hand, "
                f"{r['edge_depth_mm']}mm{proto}. Peak {r['peak_kg'] or 0} kg, working mean {r['working_mean_kg'] or 0} kg.")
        if r["notes"]:
            line += f" Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines), rows


def _climbing(conn, days):
    rows = _q(conn, """
        SELECT e.entry_date, e.title, e.notes, cs.location_type, cs.discipline,
               cs.duration_min, cs.feel_rating, cs.skin_rating, cs.session_rpe,
               COALESCE(json_agg(json_build_object(
                   'grade', c.grade, 'style', c.style, 'attempts', c.attempts, 'sent', c.sent
               ) ORDER BY c.grade_rank DESC NULLS LAST) FILTER (WHERE c.id IS NOT NULL), '[]') AS climbs
        FROM journal_entries e
        JOIN climbing_sessions cs ON cs.journal_entry_id = e.id
        LEFT JOIN climbs c ON c.climbing_session_id = cs.id
        WHERE e.entry_date >= CURRENT_DATE - %s
        GROUP BY e.id, cs.id
        ORDER BY e.entry_date
    """, (days,))
    lines = [f"## Climbing (last {days} days)"]
    if not rows:
        lines.append("- None.")
    for r in rows:
        bits = [f"{r['discipline']} at {r['location_type']}"]
        if r["duration_min"]:
            bits.append(f"{r['duration_min']} min")
        if r["feel_rating"]:
            bits.append(f"felt {r['feel_rating']}/5")
        if r["skin_rating"]:
            bits.append(f"skin {r['skin_rating']}/5")
        if r["session_rpe"]:
            bits.append(f"RPE {r['session_rpe']}")
        climbs = ", ".join(
            f"{c['grade']} ({c['style']}{'' if c['sent'] else ', not sent'}×{c['attempts']})"
            for c in r["climbs"]
        )
        line = f"- {r['entry_date']}: {', '.join(bits)}."
        if climbs:
            line += f" Climbs: {climbs}."
        if r["notes"]:
            line += f" Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines), rows


def _workouts(conn, days):
    rows = _q(conn, """
        SELECT e.entry_date, e.title, e.notes, w.workout_type, w.duration_min,
               w.session_rpe, w.details
        FROM journal_entries e
        JOIN workouts w ON w.journal_entry_id = e.id
        WHERE e.entry_date >= CURRENT_DATE - %s
        ORDER BY e.entry_date
    """, (days,))
    lines = [f"## Other workouts (last {days} days)"]
    if not rows:
        lines.append("- None.")
    for r in rows:
        bits = [r["workout_type"]]
        if r["duration_min"]:
            bits.append(f"{r['duration_min']} min")
        if r["session_rpe"]:
            bits.append(f"RPE {r['session_rpe']}")
        line = f"- {r['entry_date']}: {', '.join(bits)}."
        detail = (r["details"] or {}).get("text")
        if detail:
            line += f" {detail}."
        if r["notes"]:
            line += f" Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines), rows


def _wellness(conn, days):
    rows = _q(conn, """
        SELECT log_date, sleep_hours, sleep_quality, soreness, fatigue, motivation, notes
        FROM wellness_logs
        WHERE log_date >= CURRENT_DATE - %s
        ORDER BY log_date
    """, (days,))
    lines = [f"## Daily wellness (last {days} days; ratings 1=worst, 5=best; soreness/fatigue 1=none, 5=severe)"]
    if not rows:
        lines.append("- No check-ins.")
    for r in rows:
        bits = []
        if r["sleep_hours"] is not None:
            q = f" (quality {r['sleep_quality']}/5)" if r["sleep_quality"] else ""
            bits.append(f"sleep {r['sleep_hours']}h{q}")
        if r["soreness"]:
            bits.append(f"soreness {r['soreness']}/5")
        if r["fatigue"]:
            bits.append(f"fatigue {r['fatigue']}/5")
        if r["motivation"]:
            bits.append(f"motivation {r['motivation']}/5")
        line = f"- {r['log_date']}: {', '.join(bits) if bits else 'logged'}."
        if r["notes"]:
            line += f" Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines), rows


def _load_summary(conn):
    weekly = _q(conn, """
        WITH acts AS (
            SELECT started_at::date AS d, 'hangboard' AS kind FROM sessions
              WHERE started_at >= NOW() - INTERVAL '42 days'
            UNION ALL
            SELECT e.entry_date, e.entry_type FROM journal_entries e
              WHERE e.entry_date >= CURRENT_DATE - 42 AND e.entry_type IN ('climbing', 'workout')
        )
        SELECT date_trunc('week', d)::date AS week, kind, COUNT(*) AS n
        FROM acts GROUP BY 1, 2 ORDER BY 1
    """)
    active_days = _q(conn, """
        SELECT DISTINCT d FROM (
            SELECT started_at::date AS d FROM sessions
            UNION
            SELECT entry_date FROM journal_entries WHERE entry_type IN ('climbing', 'workout')
        ) t
        WHERE d >= CURRENT_DATE - 21
        ORDER BY d
    """)

    lines = ["## Training load"]
    weeks = {}
    for r in weekly:
        weeks.setdefault(r["week"], {})[r["kind"]] = r["n"]
    for week, kinds in sorted(weeks.items()):
        parts = ", ".join(f"{k}: {n}" for k, n in sorted(kinds.items()))
        lines.append(f"- Week of {week}: {parts}")
    if not weeks:
        lines.append("- No sessions in the last 6 weeks.")

    days_active = {r["d"] for r in active_days}
    today = date.today()
    rest_gap = None
    for i in range(21):
        d = today - timedelta(days=i)
        if d not in days_active:
            rest_gap = i
            break
    if rest_gap is not None:
        lines.append(f"- Most recent full rest day: {'today' if rest_gap == 0 else f'{rest_gap} day(s) ago'}")

    return "\n".join(lines), {"weekly": weekly, "rest_gap_days": rest_gap}
