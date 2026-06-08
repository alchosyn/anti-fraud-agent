from __future__ import annotations

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    message: str
    message_type: str = "sms"  # sms | email | phone_transcript


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
    verdict: str
    confidence: float
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
    steps: list[StepMessage]
    created_at: str
