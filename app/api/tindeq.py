"""JSON endpoints for Tindeq session data (feeds the charts)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import db
from app.repos import tindeq as repo

router = APIRouter(tags=["tindeq"])


@router.get("/sessions/{session_id}/trace")
def session_trace(session_id: int, max_points: int = Query(4000, ge=100, le=50000), conn=Depends(db)):
    session = repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    t, force = repo.get_session_trace(conn, session_id, max_points=max_points)
    return {"t": t, "force": force, "peak": session["peak_force_kg"]}


@router.get("/trends/baselines")
def baseline_trends(conn=Depends(db)):
    return {"baselines": repo.list_baselines(conn)}


@router.get("/trends/session-peaks")
def session_peak_trends(conn=Depends(db)):
    return {"peaks": repo.session_peaks_by_grip(conn)}
