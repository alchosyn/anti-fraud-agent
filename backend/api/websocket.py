from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..agent.integration import run_agent
from ..db import models
from .routes import active_sessions

router = APIRouter()


@router.websocket("/api/ws/{session_id}")
async def ws_agent(ws: WebSocket, session_id: str):
    await ws.accept()

    session_info = active_sessions.pop(session_id, None)
    if not session_info:
        await ws.send_json({"type": "error", "message": "Session not found or already consumed"})
        await ws.close()
        return

    try:
        agent_gen = run_agent(session_info["message"], session_info["message_type"])

        async for msg in agent_gen:
            await ws.send_json(msg)

            if msg["type"] == "step":
                await models.save_step(
                    session_id=session_id,
                    step_number=msg["step_number"],
                    total_steps=msg["total_steps"],
                    thought=msg["thought"],
                    tool_name=msg["tool_name"],
                    tool_input=msg["tool_input"],
                    tool_output=msg["tool_output"],
                    timestamp=msg["timestamp"],
                )
            elif msg["type"] == "result":
                await models.save_result(
                    session_id=session_id,
                    verdict=msg["verdict"],
                    confidence=msg["confidence"],
                    summary=msg["summary"],
                    advice=msg["advice"],
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
