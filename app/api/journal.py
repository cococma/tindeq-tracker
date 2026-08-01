"""Journal pages + form handlers (server-rendered, POST/redirect)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import db
from app.api.pages import render
from app.api.plan import safe_next
from app.repos import journal as repo

router = APIRouter(include_in_schema=False)

CLIMB_STYLES = ["flash", "onsight", "redpoint", "repeat", "attempt"]
DISCIPLINES = ["boulder", "sport", "trad", "board", "gym_rope"]
WORKOUT_TYPES = ["lifting", "cardio", "antagonist", "core", "mobility", "other"]


# ── Form parsing ──────────────────────────────────────────────────────────────

def _opt_int(v):
    v = (v or "").strip()
    return int(v) if v else None


def _opt_float(v):
    v = (v or "").strip()
    return float(v) if v else None


def _parse_entry_form(form):
    entry_type = form.get("entry_type", "note")
    entry = {
        "entry_date": form.get("entry_date") or date.today().isoformat(),
        "entry_type": entry_type,
        "title": (form.get("title") or "").strip() or None,
        "notes": (form.get("notes") or "").strip() or None,
    }
    climbing = climbs = workout = None

    if entry_type == "climbing":
        climbing = {
            "location_type": form.get("location_type", "gym"),
            "location": (form.get("location") or "").strip() or None,
            "discipline": form.get("discipline", "boulder"),
            "duration_min": _opt_int(form.get("duration_min")),
            "feel_rating": _opt_int(form.get("feel_rating")),
            "skin_rating": _opt_int(form.get("skin_rating")),
            "session_rpe": _opt_int(form.get("session_rpe")),
        }
        climbs = []
        grades = form.getlist("climb_grade")
        styles = form.getlist("climb_style")
        attempts = form.getlist("climb_attempts")
        names = form.getlist("climb_name")
        for i, grade in enumerate(grades):
            if not grade.strip():
                continue
            climbs.append({
                "grade": grade,
                "style": styles[i] if i < len(styles) else None,
                "attempts": _opt_int(attempts[i] if i < len(attempts) else None) or 1,
                "name": (names[i] if i < len(names) else "").strip() or None,
            })
    elif entry_type == "workout":
        details_text = (form.get("details_text") or "").strip()
        workout = {
            "workout_type": form.get("workout_type", "other"),
            "duration_min": _opt_int(form.get("duration_min")),
            "session_rpe": _opt_int(form.get("session_rpe")),
            "details": {"text": details_text} if details_text else {},
        }

    return entry, climbing, climbs, workout


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/journal", response_class=HTMLResponse)
def journal(request: Request, conn=Depends(db)):
    today = date.today()
    return render(
        request, "journal.html",
        today=today.isoformat(),
        wellness_today=repo.get_wellness(conn, today),
        active="journal",
    )


@router.get("/journal/new", response_class=HTMLResponse)
def new_entry(request: Request, type: str = "note", date_: str = Query("", alias="date"), next: str = ""):
    return render(
        request, "entry_form.html",
        entry=None, today=date_ or date.today().isoformat(),
        preselect_type=type if type in ("climbing", "workout", "note") else "note",
        next=safe_next(next, fallback="/journal"),
        climb_styles=CLIMB_STYLES, disciplines=DISCIPLINES, workout_types=WORKOUT_TYPES,
        active="journal",
    )


@router.post("/journal/new")
async def create_entry(request: Request, conn=Depends(db)):
    form = await request.form()
    entry, climbing, climbs, workout = _parse_entry_form(form)
    repo.create_entry(conn, entry, climbing=climbing, climbs=climbs, workout=workout)
    return RedirectResponse(safe_next(form.get("next"), fallback="/journal"), status_code=303)


@router.get("/journal/{entry_id}/edit", response_class=HTMLResponse)
def edit_entry(request: Request, entry_id: int, next: str = "", conn=Depends(db)):
    entry = repo.get_entry(conn, entry_id)
    if entry is None:
        raise HTTPException(404)
    return render(
        request, "entry_form.html",
        entry=entry, today=date.today().isoformat(),
        preselect_type=entry["entry_type"],
        next=safe_next(next, fallback="/journal"),
        climb_styles=CLIMB_STYLES, disciplines=DISCIPLINES, workout_types=WORKOUT_TYPES,
        active="journal",
    )


@router.post("/journal/{entry_id}/edit")
async def save_entry(request: Request, entry_id: int, conn=Depends(db)):
    if repo.get_entry(conn, entry_id) is None:
        raise HTTPException(404)
    form = await request.form()
    entry, climbing, climbs, workout = _parse_entry_form(form)
    repo.update_entry(conn, entry_id, entry, climbing=climbing, climbs=climbs, workout=workout)
    return RedirectResponse(safe_next(form.get("next"), fallback="/journal"), status_code=303)


@router.post("/journal/{entry_id}/delete")
async def remove_entry(request: Request, entry_id: int, conn=Depends(db)):
    form = await request.form()
    repo.delete_entry(conn, entry_id)
    return RedirectResponse(safe_next(form.get("next"), fallback="/journal"), status_code=303)


@router.post("/journal/wellness")
async def save_wellness(request: Request, conn=Depends(db)):
    form = await request.form()
    repo.upsert_wellness(conn, {
        "log_date": form.get("log_date") or date.today().isoformat(),
        "sleep_hours": _opt_float(form.get("sleep_hours")),
        "sleep_quality": _opt_int(form.get("sleep_quality")),
        "soreness": _opt_int(form.get("soreness")),
        "fatigue": _opt_int(form.get("fatigue")),
        "motivation": _opt_int(form.get("motivation")),
        "notes": (form.get("notes") or "").strip() or None,
    })
    return RedirectResponse("/journal", status_code=303)


# ── JSON for charts ───────────────────────────────────────────────────────────

@router.get("/api/climbing/volume")
def climbing_volume(conn=Depends(db)):
    return {"climbs": repo.climb_volume(conn)}


@router.get("/api/load/summary")
def load_summary(days: int = 84, conn=Depends(db)):
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH acts AS (
                SELECT started_at::date AS d, 'hangboard' AS kind FROM sessions
                  WHERE started_at >= NOW() - make_interval(days => %s)
                UNION ALL
                SELECT entry_date, entry_type FROM journal_entries
                  WHERE entry_date >= CURRENT_DATE - %s AND entry_type IN ('climbing', 'workout')
            )
            SELECT date_trunc('week', d)::date AS week, kind, COUNT(*) AS n
            FROM acts GROUP BY 1, 2 ORDER BY 1
            """,
            (days, days),
        )
        weekly = cur.fetchall()
    return {"weekly": weekly, "wellness": repo.list_wellness(conn, days=days)}
