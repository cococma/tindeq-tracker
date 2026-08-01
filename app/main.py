"""TrainingJournal web app."""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import capture, coach, journal, metrics, pages, plan, tindeq
from app.services import renpho_sync

BASE_DIR = os.path.dirname(__file__)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@asynccontextmanager
async def lifespan(app):
    # Opportunistic Renpho sync on startup (skipped when fresh or unconfigured);
    # failures land in sync_state and show on the Body page.
    async def startup_sync():
        try:
            await asyncio.to_thread(renpho_sync.sync_if_stale)
        except Exception:
            pass
    asyncio.create_task(startup_sync())
    yield


app = FastAPI(title="TrainingJournal", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

app.include_router(pages.router)
app.include_router(journal.router)
app.include_router(metrics.router)
app.include_router(plan.router)
app.include_router(coach.router)
app.include_router(tindeq.router, prefix="/api")
app.include_router(capture.router, prefix="/api")
