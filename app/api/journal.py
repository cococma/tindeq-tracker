"""Journal pages + form handlers (server-rendered, POST/redirect)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import db
from app.api.pages import render
from app.repos import journal as repo
from app.repos import tindeq as tindeq_repo

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
    entries = repo.list_entries(conn, limit=100)
    hangboard = tindeq_repo.list_sessions(conn, limit=100)

    # Merge journal entries and hangboard sessions into one timeline, newest first.
    items = [{"kind": "entry", "date": e["entry_date"], "e": e} for e in entries]
    items += [{"kind": "hangboard", "date": s["started_at"].date(), "e": s} for s in hangboard]
    items.sort(key=lambda i: (i["date"], i["e"].get("id", 0)), reverse=True)

    today = date.today()
    return render(
        request, "journal.html",
        items=items,
        today=today.isoformat(),
        wellness_today=repo.get_wellness(conn, today),
        active="journal",
    )


@router.get("/journal/new", response_class=HTMLResponse)
def new_entry(request: Request):
    return render(
        request, "entry_form.html",
        entry=None, today=date.today().isoformat(),
        climb_styles=CLIMB_STYLES, disciplines=DISCIPLINES, workout_types=WORKOUT_TYPES,
        active="journal",
    )


@router.post("/journal/new")
async def create_entry(request: Request, conn=Depends(db)):
    form = await request.form()
    entry, climbing, climbs, workout = _parse_entry_form(form)
    repo.create_entry(conn, entry, climbing=climbing, climbs=climbs, workout=workout)
    return RedirectResponse("/journal", status_code=303)


@router.get("/journal/{entry_id}/edit", response_class=HTMLResponse)
def edit_entry(request: Request, entry_id: int, conn=Depends(db)):
    entry = repo.get_entry(conn, entry_id)
    if entry is None:
        raise HTTPException(404)
    return render(
        request, "entry_form.html",
        entry=entry, today=date.today().isoformat(),
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
    return RedirectResponse("/journal", status_code=303)


@router.post("/journal/{entry_id}/delete")
def remove_entry(entry_id: int, conn=Depends(db)):
    repo.delete_entry(conn, entry_id)
    return RedirectResponse("/journal", status_code=303)


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


@router.get("/climbing", response_class=HTMLResponse)
def climbing_page(request: Request):
    return render(request, "climbing.html", active="climbing")


# ── JSON for charts ───────────────────────────────────────────────────────────

@router.get("/api/climbing/volume")
def climbing_volume(conn=Depends(db)):
    return {"climbs": repo.climb_volume(conn)}
