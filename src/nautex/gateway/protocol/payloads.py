"""Typed payload models for all gateway WebSocket routes.

Each payload has a `payload_type` literal discriminator so the envelope
can deserialize into the correct type automatically.

All fields are explicitly typed — no Dict[str, Any] bags.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Union

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

class EnvironmentDescriptor(BaseModel):
    """Inbound descriptor from a connecting gateway node."""
    hostname: str
    platform: str
    directory_scope: str
    username: str


class AgentDescriptorPayload(BaseModel):
    """Agent descriptor sent in registration payload."""
    agent_id: str
    executable: str
    name: str = ""


class NodeRegistrationPayload(BaseModel):
    """Rich registration sent once on node connect."""
    payload_type: Literal["node_registration"] = "node_registration"
    utility_instance_id: str
    environment: EnvironmentDescriptor
    agents: List[AgentDescriptorPayload] = []
    environment_id: Optional[str] = None


class HeartbeatPayload(BaseModel):
    payload_type: Literal["heartbeat"] = "heartbeat"
    utility_instance_id: str
    active_sessions_count: int
    status: NodeStatus = NodeStatus.HEALTHY


class PermissionRequestPayload(BaseModel):
    payload_type: Literal["permission_request"] = "permission_request"
    permission_id: str
    session_id: Optional[str] = None        # backend's canonical session ID
    acp_session_id: str = ""
    tool_name: str
    tool_kind: Optional[ToolKind] = None
    path: Optional[str] = None
    command: Optional[str] = None


class ConsolidatedSessionUpdate(BaseModel):
    """Semantic batched update from an agent stream.

    The strict public boundary type — adapters yield only this.
    Also serves as the WS payload for session updates (payload_type discriminator).
    Reference: MDS-35
    """
    payload_type: Literal["session_update"] = "session_update"
    kind: SessionUpdateKind
    session_id: Optional[str] = None        # backend's canonical session ID (set by gateway for backend-initiated)
    acp_session_id: Optional[str] = None    # agent's native session ID
    text: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_title: Optional[str] = None
    tool_status: Optional[ToolCallStatus] = None
    tool_kind: Optional[ToolKind] = None
    session_title: Optional[str] = None
    mode_id: Optional[str] = None
    commands_count: Optional[int] = None
    usage_size: Optional[int] = None
    usage_used: Optional[int] = None


class TelemetryPayload(BaseModel):
    payload_type: Literal["telemetry"] = "telemetry"
    acp_session_id: str
    active_tool: Optional[str] = None
    processed_tokens_estimate: int = 0
    is_typing: bool = False


# ---------------------------------------------------------------------------
# Frontend/Backend → Utility payloads
# ---------------------------------------------------------------------------

class PermissionResponsePayload(BaseModel):
    payload_type: Literal["permission_response"] = "permission_response"
    permission_id: str
    acp_session_id: str = ""
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


class RegistrationAckPayload(BaseModel):
    """Backend → node ack after registration with resolved environment_id."""
    payload_type: Literal["registration_ack"] = "registration_ack"
    environment_id: str


# ---------------------------------------------------------------------------
# Discriminated union of all payloads
# ---------------------------------------------------------------------------

GatewayPayload = Union[
    NodeRegistrationPayload,
    HeartbeatPayload,
    PermissionRequestPayload,
    ConsolidatedSessionUpdate,
    TelemetryPayload,
    PermissionResponsePayload,
    ExecutePromptPayload,
    CancelSessionPayload,
    SearchRequestPayload,
    SearchResponsePayload,
    RegistrationAckPayload,
]

PAYLOAD_DISCRIMINATOR = "payload_type"
