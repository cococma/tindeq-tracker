"""Server-rendered HTML pages."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import json

from app.api.deps import db
from app.constants import (
    BASELINE_DEFAULTS, EXERCISE_DEFAULTS, EXERCISE_OPTIONS, GRIP_OPTIONS,
    HAND_OPTIONS,
)
from app.repos import metrics as metrics_repo
from app.repos import plan as plan_repo
from app.repos import tindeq as repo
from app.services import renpho_sync

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
    resp = _templates(request).TemplateResponse(request, name, ctx)
    # Pages must never be served from browser cache — Chrome restores closed
    # tabs from cache, resurrecting stale JS after the app updates.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, msg: str = "", conn=Depends(db)):
    return render(
        request, "dashboard.html",
        stats=repo.dashboard_stats(conn),
        latest=metrics_repo.latest_metrics(conn),
        sync_state=metrics_repo.get_sync_state(conn, "renpho"),
        creds_configured=renpho_sync.credentials_configured(),
        msg=msg,
        active="dashboard",
    )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
def session_detail(request: Request, session_id: int, conn=Depends(db)):
    session = repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    duration_s = None
    if session["ended_at"] and session["started_at"]:
        duration_s = int((session["ended_at"] - session["started_at"]).total_seconds())
    return render(request, "session_detail.html", session=session, duration_s=duration_s, active="capture")


@router.post("/sessions/{session_id}/delete")
def delete_session(session_id: int, conn=Depends(db)):
    if not repo.delete_session(conn, session_id):
        raise HTTPException(404, "session not found")
    return RedirectResponse("/capture", status_code=303)


@router.get("/trends", response_class=HTMLResponse)
def trends(request: Request):
    return render(request, "trends.html", active="trends")


@router.get("/capture", response_class=HTMLResponse)
def capture(request: Request, plan: int = 0, conn=Depends(db)):
    # ?plan=<id> opens the page with a planned session's setup already filled in
    # (the calendar links here). An unknown or setup-less item just renders the
    # normal blank form.
    plan_item = plan_repo.get_item(conn, plan) if plan else None
    if plan_item and not plan_item.get("prescription"):
        plan_item = None
    if plan_item and not plan_item["prescription"].get("notes"):
        # What was planned is worth carrying into the session's notes.
        plan_item["prescription"]["notes"] = plan_item["details"] or plan_item["title"]
    return render(
        request,
        "capture.html",
        exercise_options=EXERCISE_OPTIONS,
        grip_options=GRIP_OPTIONS,
        hand_options=HAND_OPTIONS,
        exercise_defaults_json=json.dumps(EXERCISE_DEFAULTS),
        baseline_defaults_json=json.dumps(BASELINE_DEFAULTS),
        plan_item=plan_item,
        plan_prescription_json=json.dumps(plan_item["prescription"] if plan_item else None),
        recent=repo.list_sessions(conn, limit=30),
        active="capture",
    )
