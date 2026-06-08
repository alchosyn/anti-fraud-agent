from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..schemas import AnalyzeRequest, AnalyzeResponse, HistoryListResponse, SessionDetail
from ..db import models
from ..agent.integration import run_mock_agent

router = APIRouter(prefix="/api")

# In-memory store of active sessions' async generators, keyed by session_id.
# The WebSocket handler consumes these.
active_sessions: dict[str, dict] = {}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    await models.create_session(session_id, req.message, req.message_type)

    active_sessions[session_id] = {
        "message": req.message,
        "message_type": req.message_type,
    }

    return AnalyzeResponse(session_id=session_id)


@router.get("/history", response_model=HistoryListResponse)
async def history():
    records = await models.get_history()
    return HistoryListResponse(records=records)


@router.get("/history/{session_id}", response_model=SessionDetail)
async def session_detail(session_id: str):
    detail = await models.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(**detail)
