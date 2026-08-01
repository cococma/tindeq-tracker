"""Training calendar: month grid, planned items, training blocks, coach proposals."""

import calendar as pycal
from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.api.deps import db
from app.api.pages import render
from app.repos import plan as repo

router = APIRouter(include_in_schema=False)

PLAN_ITEM_TYPES = ["hangboard", "climbing", "workout", "rest", "other"]

DateType = date  # the models below have a field literally named `date`


def safe_next(target, fallback="/calendar"):
    """Only allow same-site relative redirect targets."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return fallback


def _parse_item(form):
    item_type = form.get("item_type", "other")
    if item_type not in PLAN_ITEM_TYPES:
        raise HTTPException(400, f"unknown item type: {item_type}")
    title = (form.get("title") or "").strip()
    return {
        "plan_date": form.get("plan_date") or date.today().isoformat(),
        "item_type": item_type,
        "title": title or item_type.title(),
        "details": (form.get("details") or "").strip() or None,
    }


def _parse_block(form):
    name = (form.get("name") or "").strip()
    start = form.get("start_date") or ""
    end = form.get("end_date") or ""
    if not (name and start and end):
        raise HTTPException(400, "block needs a name, start date, and end date")
    if end < start:
        raise HTTPException(400, "block end date is before its start date")
    return {
        "name": name,
        "start_date": start,
        "end_date": end,
        "focus": (form.get("focus") or "").strip() or None,
    }


# ── Page ──────────────────────────────────────────────────────────────────────

@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, year: int = 0, month: int = 0, day: str = "", conn=Depends(db)):
    today = date.today()
    year = year or today.year
    month = month or today.month
    try:
        week_dates = pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)
    except pycal.IllegalMonthError:
        raise HTTPException(404, "no such month")

    selected = None
    if day:
        try:
            selected = date.fromisoformat(day)
        except ValueError:
            pass

    grid_start, grid_end = week_dates[0][0], week_dates[-1][-1]
    facts = repo.month_facts(conn, grid_start, grid_end)

    planned_by_day = {}
    for item in repo.list_items(conn, grid_start, grid_end):
        planned_by_day.setdefault(item["plan_date"], []).append(item)

    blocks = repo.list_blocks(conn)
    weeks = []
    for days in week_dates:
        bands = []
        for b in blocks:
            if b["start_date"] > days[-1] or b["end_date"] < days[0]:
                continue
            start_col = max((b["start_date"] - days[0]).days, 0) + 1
            end_col = min((b["end_date"] - days[0]).days, 6) + 2  # grid-column end is exclusive
            bands.append({
                **b,
                "col_start": start_col,
                "col_end": end_col,
                "cont_left": b["start_date"] < days[0],
                "cont_right": b["end_date"] > days[-1],
            })
        weeks.append({"days": days, "bands": bands})

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)

    return render(
        request, "calendar.html",
        year=year, month=month,
        month_label=date(year, month, 1).strftime("%B %Y"),
        prev_url=f"/calendar?year={prev_y}&month={prev_m}",
        next_url=f"/calendar?year={next_y}&month={next_m}",
        weeks=weeks,
        facts=facts,
        planned_by_day=planned_by_day,
        blocks=blocks,
        today=today,
        selected=selected,
        detail=repo.day_detail(conn, selected) if selected else None,
        plan_item_types=PLAN_ITEM_TYPES,
        active="calendar",
    )


# ── Planned item forms ────────────────────────────────────────────────────────

@router.post("/plan/new")
async def create_item(request: Request, conn=Depends(db)):
    form = await request.form()
    repo.create_item(conn, _parse_item(form))
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


@router.post("/plan/{item_id}/edit")
async def save_item(request: Request, item_id: int, conn=Depends(db)):
    form = await request.form()
    if not repo.update_item(conn, item_id, _parse_item(form)):
        raise HTTPException(404, "planned item not found")
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


@router.post("/plan/{item_id}/delete")
async def remove_item(request: Request, item_id: int, conn=Depends(db)):
    form = await request.form()
    repo.delete_item(conn, item_id)
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


# ── Training block forms ──────────────────────────────────────────────────────

@router.post("/plan/blocks/new")
async def create_block(request: Request, conn=Depends(db)):
    form = await request.form()
    repo.create_block(conn, _parse_block(form))
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


@router.post("/plan/blocks/{block_id}/edit")
async def save_block(request: Request, block_id: int, conn=Depends(db)):
    form = await request.form()
    if not repo.update_block(conn, block_id, _parse_block(form)):
        raise HTTPException(404, "training block not found")
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


@router.post("/plan/blocks/{block_id}/delete")
async def remove_block(request: Request, block_id: int, conn=Depends(db)):
    form = await request.form()
    repo.delete_block(conn, block_id)
    return RedirectResponse(safe_next(form.get("next")), status_code=303)


# ── JSON ──────────────────────────────────────────────────────────────────────

@router.get("/api/plan")
def plan_range(start: date, end: date, conn=Depends(db)):
    return {
        "items": repo.list_items(conn, start, end),
        "blocks": repo.list_blocks(conn, start, end),
    }


# ── Coach proposals ───────────────────────────────────────────────────────────
#
# This endpoint is the ONLY path coach output takes into the calendar, so the
# "coach can never touch the past" rule lives here unconditionally. The user's
# own /plan/* form endpoints have no date restriction.

class ProposalItem(BaseModel):
    action: Literal["add", "update", "delete"]
    id: Optional[int] = None
    date: Optional[DateType] = None
    type: Optional[str] = None
    title: Optional[str] = None
    details: Optional[str] = None


class ProposalBlock(BaseModel):
    action: Literal["add", "update", "delete"]
    id: Optional[int] = None
    name: Optional[str] = None
    start: Optional[DateType] = None
    end: Optional[DateType] = None
    focus: Optional[str] = None


class Proposal(BaseModel):
    summary: str = ""
    items: List[ProposalItem] = []
    blocks: List[ProposalBlock] = []


def _past(label):
    raise HTTPException(400, f"proposal touches past dates: {label} — past days cannot be edited")


@router.post("/api/plan/apply-proposal")
def apply_proposal(proposal: Proposal, conn=Depends(db)):
    today = date.today()
    item_ops, block_ops = [], []

    for it in proposal.items:
        if it.action == "add":
            if not it.date or it.type not in PLAN_ITEM_TYPES:
                raise HTTPException(400, "item add needs a date and a valid type")
            if it.date < today:
                _past(it.date.isoformat())
            item_ops.append(("add", {
                "plan_date": it.date,
                "item_type": it.type,
                "title": (it.title or "").strip() or it.type.title(),
                "details": (it.details or "").strip() or None,
            }))
        else:
            if not it.id:
                raise HTTPException(400, f"item {it.action} needs an id")
            existing = repo.get_item(conn, it.id)
            if existing is None:
                raise HTTPException(400, f"planned item id {it.id} does not exist (stale id?)")
            if existing["plan_date"] < today:
                _past(f"item {it.id} on {existing['plan_date']}")
            if it.action == "delete":
                item_ops.append(("delete", {"id": it.id}))
                continue
            new_date = it.date or existing["plan_date"]
            new_type = it.type or existing["item_type"]
            if new_date < today:
                _past(new_date.isoformat())
            if new_type not in PLAN_ITEM_TYPES:
                raise HTTPException(400, f"unknown item type: {new_type}")
            item_ops.append(("update", {
                "id": it.id,
                "plan_date": new_date,
                "item_type": new_type,
                "title": (it.title or "").strip() or existing["title"],
                "details": it.details.strip() if it.details is not None else existing["details"],
            }))

    for b in proposal.blocks:
        if b.action == "add":
            if not (b.name and b.start and b.end):
                raise HTTPException(400, "block add needs a name, start, and end")
            if b.start < today:
                _past(b.start.isoformat())
            if b.end < b.start:
                raise HTTPException(400, "block end date is before its start date")
            block_ops.append(("add", {
                "name": b.name.strip(),
                "start_date": b.start,
                "end_date": b.end,
                "focus": (b.focus or "").strip() or None,
            }))
        else:
            if not b.id:
                raise HTTPException(400, f"block {b.action} needs an id")
            existing = repo.get_block(conn, b.id)
            if existing is None:
                raise HTTPException(400, f"training block id {b.id} does not exist (stale id?)")
            if existing["start_date"] < today:
                _past(f"block {b.id} starting {existing['start_date']}")
            if b.action == "delete":
                block_ops.append(("delete", {"id": b.id}))
                continue
            new_start = b.start or existing["start_date"]
            new_end = b.end or existing["end_date"]
            if new_start < today:
                _past(new_start.isoformat())
            if new_end < new_start:
                raise HTTPException(400, "block end date is before its start date")
            block_ops.append(("update", {
                "id": b.id,
                "name": (b.name or "").strip() or existing["name"],
                "start_date": new_start,
                "end_date": new_end,
                "focus": b.focus.strip() if b.focus is not None else existing["focus"],
            }))

    if not item_ops and not block_ops:
        raise HTTPException(400, "proposal contains no actions")

    return {"applied": repo.apply_proposal(conn, item_ops, block_ops)}
