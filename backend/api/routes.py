from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import (
    AnalyzeRequest, AnalyzeResponse,
    HistoryListResponse, SessionDetail,
    RegisterRequest, LoginRequest, TokenResponse, UserInfo,
)
from ..db import models
from ..db.database import get_session
from ..auth import (
    hash_password, verify_password,
    create_access_token, get_current_user,
)
from ..services.cache import get_cached_analysis
from ..services.pending import put_pending
from ..services.rate_limit import rate_limit

router = APIRouter(prefix="/api")


# ===================================================================
# Auth routes (public — no token required)
# ===================================================================

@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("register", limit=5, window_s=300))],
)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_session)):
    if len(req.username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    existing = await models.get_user_by_username(db, req.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    # bcrypt ~200ms 且为 CPU 密集：丢线程池，不阻塞事件循环（bcrypt 释放 GIL）
    hashed = await asyncio.to_thread(hash_password, req.password)
    try:
        user_id = await models.create_user(db, req.username, hashed, req.display_name)
        await db.commit()
    except IntegrityError:
        # 并发注册同名：唯一索引兜底
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already taken")

    token = create_access_token(user_id, req.username)
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            user_id=user_id,
            username=req.username,
            display_name=req.display_name or req.username,
        ),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", limit=10, window_s=60))],
)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_session)):
    user = await models.get_user_by_username(db, req.username)
    valid = (
        await asyncio.to_thread(verify_password, req.password, user["hashed_password"])
        if user else False
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user["id"], user["username"])
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            user_id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
        ),
    )


# ===================================================================
# Protected routes (token required)
# ===================================================================

@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(rate_limit("analyze", limit=30, window_s=3600, by_user=True))],
)
async def analyze(
    req: AnalyzeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    user_id = current_user["user_id"]
    session_id = str(uuid.uuid4())
    await models.create_session(db, session_id, user_id, req.message, req.message_type)
    # 显式提交：WS 可能在本请求 teardown 之前就连上并写 tool_calls（外键依赖）
    await db.commit()

    cached = await get_cached_analysis(req.message_type, req.message) if not req.history else None
    await put_pending(session_id, {
        "message": req.message,
        "message_type": req.message_type,
        "history": [{"role": t.role, "content": t.content} for t in req.history],
        "cached_result": cached,
    })

    return AnalyzeResponse(session_id=session_id, status="cached" if cached else "processing")


@router.get("/history", response_model=HistoryListResponse)
async def history(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    records = await models.get_history(db, current_user["user_id"])
    return HistoryListResponse(records=records)


@router.get("/history/{session_id}", response_model=SessionDetail)
async def session_detail(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    detail = await models.get_session_detail(db, session_id, current_user["user_id"])
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(**detail)


@router.get("/healthz", include_in_schema=False)
async def healthz():
    """容器编排健康检查用。"""
    return {"status": "ok"}
