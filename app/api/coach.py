"""AI coach endpoints: on-demand recommendation, streaming chat, context preview."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.api.deps import db
from app.api.pages import render
from app.db import get_db_connection
from app.repos import coach as repo
from app.services import coach
from app.services.coach import CoachNotConfigured
from app.services.coach_context import build_context

router = APIRouter(include_in_schema=False)


class RecommendationRequest(BaseModel):
    constraint: str = ""


class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    message: str


@router.get("/coach", response_class=HTMLResponse)
def coach_page(request: Request, conn=Depends(db)):
    return render(
        request, "coach.html",
        conversations=repo.list_conversations(conn),
        recommendations=repo.list_recommendations(conn),
        active="coach",
    )


@router.post("/api/coach/recommendation")
async def recommendation(req: RecommendationRequest, conn=Depends(db)):
    context_md, snapshot = build_context(conn)
    try:
        text = await asyncio.to_thread(coach.get_recommendation, context_md, req.constraint)
    except CoachNotConfigured as e:
        raise HTTPException(503, str(e))
    rid = repo.save_recommendation(conn, snapshot, req.constraint or None, text, coach.MODEL)
    return {"id": rid, "recommendation": text}


@router.post("/api/coach/chat")
async def chat(req: ChatRequest, conn=Depends(db)):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "empty message")

    conversation_id = req.conversation_id
    if conversation_id is None:
        conversation_id = repo.create_conversation(conn, title=message[:80])
    elif not repo.get_messages(conn, conversation_id) and req.conversation_id is not None:
        # allow continuing an empty conversation; nothing to do
        pass

    history = repo.get_messages(conn, conversation_id)
    context_md, _ = build_context(conn)
    repo.add_message(conn, conversation_id, "user", message)

    def generate():
        chunks = []
        try:
            for chunk in coach.stream_chat(context_md, history, message):
                chunks.append(chunk)
                yield chunk
        except CoachNotConfigured as e:
            yield f"⚠ {e}"
            return
        except Exception as e:
            yield f"\n\n⚠ Coach error: {type(e).__name__}: {e}"
            return
        # Persist on our own connection — the request-scoped one is closed by now.
        conn2 = get_db_connection()
        try:
            repo.add_message(conn2, conversation_id, "assistant", "".join(chunks))
        finally:
            conn2.close()

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Conversation-Id": str(conversation_id)},
    )


@router.get("/api/coach/conversations/{conversation_id}")
def conversation_messages(conversation_id: int, conn=Depends(db)):
    return {"id": conversation_id, "messages": repo.get_messages(conn, conversation_id)}


@router.get("/api/coach/context/preview")
async def context_preview(conn=Depends(db)):
    context_md, snapshot = build_context(conn)
    tokens = None
    try:
        tokens = await asyncio.to_thread(coach.count_context_tokens, context_md)
    except Exception:
        pass  # preview must work without an API key
    return {"tokens": tokens, "markdown": context_md}
