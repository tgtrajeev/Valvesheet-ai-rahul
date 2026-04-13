"""Pydantic request/response schemas for API endpoints."""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: Optional[str] = None


class ValidateRequest(BaseModel):
    valve_type: str
    seat: str
    spec: str
    end_conn: Optional[str] = None
    bore: Optional[str] = None


class Suggestion(BaseModel):
    type: str  # next_step, fix, material, spec, combination
    title: str
    description: str
    action: dict[str, Any] = {}
    confidence: float = 0.8


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[Suggestion] = []


class AgentEvent(BaseModel):
    type: str  # thinking, tool_call, tool_result, text, suggestion, validation, datasheet, error
    data: dict[str, Any] = {}


class DatasheetResponse(BaseModel):
    id: Optional[int] = None
    vds_code: str
    datasheet: dict[str, Any]
    field_sources: dict[str, str] = {}
    validation_status: str
    completion_pct: float


class IngestRequest(BaseModel):
    doc_type: str = "auto"


class SourceInfo(BaseModel):
    id: int
    filename: str
    doc_type: str
    chunk_count: int
    ingested_at: str


class MetadataResponse(BaseModel):
    valve_types: list[dict]
    seat_types: list[dict]
    end_connections: list[dict]
    design_codes: list[dict]
    piping_specs: list[str]
