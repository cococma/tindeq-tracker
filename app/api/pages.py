"""Server-rendered HTML pages."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

import json

from app.api.deps import db
from app.constants import (
    EXERCISE_DEFAULTS, EXERCISE_OPTIONS, GRIP_OPTIONS, HAND_OPTIONS,
)
from app.repos import tindeq as repo

router = APIRouter(include_in_schema=False)

EXERCISE_LABELS = dict(EXERCISE_OPTIONS)
GRIP_LABELS = dict(GRIP_OPTIONS)


def _templates(request: Request):
    # Imported lazily to avoid a circular import with app.main
    from app.main import templates
    return templates


def render(request: Request, name: str, **ctx):
    ctx.update(
        request=request,
        exercise_labels=EXERCISE_LABELS,
        grip_labels=GRIP_LABELS,
    )
    return _templates(request).TemplateResponse(request, name, ctx)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn=Depends(db)):
    stats = repo.dashboard_stats(conn)
    recent = repo.list_sessions(conn, limit=8)
    return render(request, "dashboard.html", stats=stats, recent=recent, active="dashboard")


@router.get("/sessions", response_class=HTMLResponse)
def sessions(request: Request, conn=Depends(db)):
    return render(request, "sessions.html", sessions=repo.list_sessions(conn), active="sessions")


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
def session_detail(request: Request, session_id: int, conn=Depends(db)):
    session = repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    duration_s = None
    if session["ended_at"] and session["started_at"]:
        duration_s = int((session["ended_at"] - session["started_at"]).total_seconds())
    return render(request, "session_detail.html", session=session, duration_s=duration_s, active="sessions")


@router.get("/trends", response_class=HTMLResponse)
def trends(request: Request):
    return render(request, "trends.html", active="trends")


@router.get("/capture", response_class=HTMLResponse)
def capture(request: Request):
    return render(
        request,
        "capture.html",
        exercise_options=EXERCISE_OPTIONS,
        grip_options=GRIP_OPTIONS,
        hand_options=HAND_OPTIONS,
        exercise_defaults_json=json.dumps(EXERCISE_DEFAULTS),
        active="capture",
    )
