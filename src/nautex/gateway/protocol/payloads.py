"""Typed payload models for all gateway WebSocket routes.

Each payload has a `payload_type` literal discriminator so the envelope
can deserialize into the correct type automatically.

All fields are explicitly typed — no Dict[str, Any] bags.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .enums import (
    NodeStatus,
    PermissionAction,
    SessionUpdateKind,
    ToolCallStatus,
    ToolKind,
)


# ---------------------------------------------------------------------------
# Utility → Backend payloads
# ---------------------------------------------------------------------------

class HeartbeatPayload(BaseModel):
    payload_type: Literal["heartbeat"] = "heartbeat"
    utility_instance_id: str
    active_sessions_count: int
    status: NodeStatus = NodeStatus.HEALTHY


class PermissionRequestPayload(BaseModel):
    payload_type: Literal["permission_request"] = "permission_request"
    permission_id: str
    session_id: str = ""
    tool_name: str
    tool_kind: Optional[ToolKind] = None
    path: Optional[str] = None
    command: Optional[str] = None


class ToolCallDetail(BaseModel):
    """Structured tool call info embedded in session updates."""
    tool_call_id: str
    title: str = ""
    status: ToolCallStatus = ToolCallStatus.PENDING
    tool_kind: Optional[ToolKind] = None


class SessionUpdatePayload(BaseModel):
    payload_type: Literal["session_update"] = "session_update"
    session_id: str
    kind: SessionUpdateKind
    text: Optional[str] = None
    tool_call: Optional[ToolCallDetail] = None
    mode_id: Optional[str] = None
    commands_count: Optional[int] = None
    usage_size: Optional[int] = None
    usage_used: Optional[int] = None


class TelemetryPayload(BaseModel):
    payload_type: Literal["telemetry"] = "telemetry"
    session_id: str
    active_tool: Optional[str] = None
    processed_tokens_estimate: int = 0
    is_typing: bool = False


# ---------------------------------------------------------------------------
# Frontend/Backend → Utility payloads
# ---------------------------------------------------------------------------

class PermissionResponsePayload(BaseModel):
    payload_type: Literal["permission_response"] = "permission_response"
    permission_id: str
    session_id: str = ""
    action: PermissionAction = PermissionAction.APPROVE


class ExecutePromptPayload(BaseModel):
    payload_type: Literal["execute_prompt"] = "execute_prompt"
    session_id: str
    agent_id: str
    prompt: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None


class CancelSessionPayload(BaseModel):
    payload_type: Literal["cancel_session"] = "cancel_session"
    session_id: str


class SearchRequestPayload(BaseModel):
    payload_type: Literal["search_request"] = "search_request"
    query: str
    limit: int = 20


class SearchResultItem(BaseModel):
    """Single file match in a search response."""
    filepath: str
    score: float
    snippets: List[str] = Field(default_factory=list)


class SearchResponsePayload(BaseModel):
    payload_type: Literal["search_response"] = "search_response"
    results: List[SearchResultItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Discriminated union of all payloads
# ---------------------------------------------------------------------------

GatewayPayload = Union[
    HeartbeatPayload,
    PermissionRequestPayload,
    SessionUpdatePayload,
    TelemetryPayload,
    PermissionResponsePayload,
    ExecutePromptPayload,
    CancelSessionPayload,
    SearchRequestPayload,
    SearchResponsePayload,
]

PAYLOAD_DISCRIMINATOR = "payload_type"
