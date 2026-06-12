from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..agent.integration import run_agent
from ..auth import decode_token
from ..db import models
from ..db.database import SessionLocal
from ..services.cache import set_cached_analysis
from ..services.pending import pop_pending

router = APIRouter()


@router.websocket("/api/ws/{session_id}")
async def ws_agent(ws: WebSocket, session_id: str, token: str = Query(...)):
    # Authenticate via query param: ws://host/api/ws/{id}?token=xxx
    try:
        decode_token(token)
    except Exception:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    session_info = await pop_pending(session_id)
    if not session_info:
        await ws.send_json({"type": "error", "message": "Session not found or already consumed"})
        await ws.close()
        return

    try:
        async with SessionLocal() as db:
            # —— 缓存命中：跳过 agent 循环，直接回结果（仍然落库保历史一致）——
            cached = session_info.get("cached_result")
            if cached:
                result = {**cached, "cached": True}
                # 先落库再推送：客户端收到即已持久化
                await models.save_result(
                    db,
                    session_id=session_id,
                    verdict=result.get("verdict"),
                    confidence=result.get("confidence"),
                    summary=result.get("summary", ""),
                    advice=result.get("advice", []),
                    evidence=result.get("evidence", []),
                )
                await db.commit()
                await ws.send_json(result)
                return

            agent_gen = run_agent(
                session_info["message"],
                session_info["message_type"],
                history=session_info.get("history", []),
            )

            # 持久化在前、推送在后：客户端收到的每条消息都已落库，
            # 连接中断不会丢已推送的进度
            async for msg in agent_gen:
                if msg["type"] == "step":
                    await models.save_step(
                        db,
                        session_id=session_id,
                        step_number=msg["step_number"],
                        total_steps=msg["total_steps"],
                        thought=msg["thought"],
                        tool_name=msg["tool_name"],
                        tool_input=msg["tool_input"],
                        tool_output=msg["tool_output"],
                        timestamp=msg["timestamp"],
                    )
                    await db.commit()  # 逐步提交：中断也保留已完成步骤
                elif msg["type"] == "result":
                    await models.save_result(
                        db,
                        session_id=session_id,
                        verdict=msg["verdict"],
                        confidence=msg["confidence"],
                        summary=msg["summary"],
                        advice=msg["advice"],
                        evidence=msg.get("evidence", []),
                    )
                    await db.commit()
                    # 首轮分析（无历史上下文）才可复用 → 写缓存
                    if not session_info.get("history"):
                        await set_cached_analysis(
                            session_info["message_type"], session_info["message"], msg
                        )

                await ws.send_json(msg)

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
