from __future__ import annotations

from pydantic import BaseModel


# ── Auth ──

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    user_id: int
    username: str
    display_name: str


# ── Chat ──

class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AnalyzeRequest(BaseModel):
    message: str
    message_type: str = "sms"  # sms | email | phone_transcript
    history: list[ChatTurn] = []  # previous conversation turns for context


class AnalyzeResponse(BaseModel):
    session_id: str
    status: str = "processing"


class StepMessage(BaseModel):
    type: str = "step"
    step_number: int
    total_steps: int
    thought: str
    tool_name: str
    tool_input: dict
    tool_output: dict
    timestamp: str


class ResultMessage(BaseModel):
    type: str = "result"
    verdict: str | None = None
    confidence: float | None = None
    summary: str
    advice: list[str]
    evidence: list[dict]


class ErrorMessage(BaseModel):
    type: str = "error"
    message: str


class HistoryRecord(BaseModel):
    session_id: str
    message_preview: str
    message_type: str
    verdict: str | None
    created_at: str


class HistoryListResponse(BaseModel):
    records: list[HistoryRecord]


class SessionDetail(BaseModel):
    session_id: str
    message: str
    message_type: str
    verdict: str | None
    confidence: float | None
    summary: str | None
    advice: list[str]
    evidence: list[dict] = []
    steps: list[StepMessage]
    created_at: str
