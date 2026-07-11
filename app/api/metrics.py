"""Body metrics: page, chart series, Renpho sync + CSV import."""

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import db
from app.api.pages import render
from app.repos import metrics as repo
from app.services import renpho_sync
from app.services.renpho_csv import parse_renpho_csv

router = APIRouter(include_in_schema=False)


@router.get("/body", response_class=HTMLResponse)
def body_page(request: Request, msg: str = "", conn=Depends(db)):
    return render(
        request, "body.html",
        latest=repo.latest_metrics(conn),
        metrics=repo.available_metrics(conn),
        sync_state=repo.get_sync_state(conn, "renpho"),
        creds_configured=renpho_sync.credentials_configured(),
        msg=msg,
        active="body",
    )


@router.post("/body/sync")
async def run_sync(request: Request):
    import asyncio
    result = await asyncio.to_thread(renpho_sync.sync)
    return RedirectResponse(f"/body?msg={result['status']}", status_code=303)


@router.post("/body/import")
async def import_csv(file: UploadFile, conn=Depends(db)):
    try:
        text = (await file.read()).decode("utf-8-sig")  # Renpho exports may carry a BOM
        rows, skipped = parse_renpho_csv(text)
        inserted = repo.insert_metrics(conn, rows) if rows else 0
        msg = f"Imported {inserted} new values from {file.filename}"
        if len(rows) - inserted:
            msg += f" ({len(rows) - inserted} already present)"
        if skipped:
            msg += f" · {skipped} rows skipped"
    except Exception as e:
        msg = f"Import failed: {e}"
    return RedirectResponse(f"/body?msg={msg}", status_code=303)


@router.get("/api/metrics/series")
def series(metric: str, conn=Depends(db)):
    return {"metric": metric, "points": repo.metric_series(conn, metric)}
