"""Capture control endpoints + live WebSocket feed."""

from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.services.capture import CaptureBusy, manager

router = APIRouter(tags=["capture"])


class CaptureConfig(BaseModel):
    exercise_type: str
    grip_type: str = "half_crimp"
    hand: str = "right"
    edge_depth_mm: int = 20
    target_weight_kg: float = 0
    on_seconds: Optional[int] = None
    off_seconds: Optional[int] = None
    target_sets: Optional[int] = None
    target_reps: Optional[int] = None
    set_rest_s: int = 180
    target_duration_s: Optional[int] = None
    target_pull_reps: Optional[int] = None
    no_record: bool = False
    notes: Optional[str] = None
    simulate: bool = False  # dev: synthetic force source instead of BLE


@router.post("/capture/start")
async def start_capture(cfg: CaptureConfig):
    # async so manager.start() runs on the event loop (it creates asyncio primitives)
    try:
        manager.start(cfg.model_dump())
    except CaptureBusy as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@router.post("/capture/stop")
async def stop_capture():
    manager.request_stop()
    return {"ok": True}


@router.get("/capture/status")
async def capture_status():
    return manager.status()


@router.websocket("/capture/ws")
async def capture_ws(ws: WebSocket):
    await ws.accept()
    q = manager.subscribe()
    try:
        await ws.send_json({"type": "status", **manager.status()})
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(q)
