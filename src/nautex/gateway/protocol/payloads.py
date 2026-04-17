"""Typed payload models for all gateway WebSocket routes.

Each payload has a `payload_type` literal discriminator so the envelope
can deserialize into the correct type automatically.

All fields are explicitly typed — no Dict[str, Any] bags.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .enums import (
    AgentLifecycleEvent,
    NodeStatus,
    PermissionAction,
    PermissionMode,
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
    node_instance_id: str
    environment: EnvironmentDescriptor
    agents: List[AgentDescriptorPayload] = []
    environment_id: Optional[str] = None


class HeartbeatPayload(BaseModel):
    payload_type: Literal["heartbeat"] = "heartbeat"
    node_instance_id: str
    active_sessions_count: int
    status: NodeStatus = NodeStatus.HEALTHY


class PermissionRequestPayload(BaseModel):
    payload_type: Literal["permission_request"] = "permission_request"
    permission_id: str
    session_id: Optional[str] = None        # backend's canonical session ID
    acp_session_id: str = ""
    tool_name: str
    tool_kind: Optional[ToolKind] = None
    tool_call_id: Optional[str] = None      # ACP tool call this permission gates
    path: Optional[str] = None
    command: Optional[str] = None
    # Set by the adapter when the session policy already decided the outcome.
    # Backend records the permission item in its terminal state (no UI prompt)
    # and immediately responds with this action.
    policy_action: Optional[PermissionAction] = None


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
    turn_id: Optional[str] = None              # synthesized by gateway per prompt dispatch
    acp_message_id: Optional[str] = None       # preserved from ACP ContentChunk.message_id


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


class SessionDeclaredPayload(BaseModel):
    """Node declares a session it started independently (TUI, auto-start).

    Backend creates the session record, assigns canonical session_id,
    and acknowledges back with the mapping.
    """
    payload_type: Literal["session_declared"] = "session_declared"
    acp_session_id: str  # agent's internal session ID
    agent_id: str


class SessionAcknowledgedPayload(BaseModel):
    """Backend acknowledges a declared session — sends canonical session_id back to node.

    Node should use session_id (backend's) in subsequent CSUs.
    Backend also reconciles via acp_session_id if node keeps using it.
    """
    payload_type: Literal["session_acknowledged"] = "session_acknowledged"
    session_id: str       # backend's canonical ID
    acp_session_id: str   # echoed back for node's mapping


class MCPServerEntry(BaseModel):
    """MCP server to inject at session start."""
    server_id: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: dict = Field(default_factory=dict)


class SessionConfigPayload(BaseModel):
    """Session-intent configuration sent from backend to gateway at spawn time.

    Controls what MCP servers are injected, what instructions the agent receives,
    and what capabilities are allowed. Gateway merges these into AgentSessionConfig.

    permissions is keyed by ACP ToolKind. Scopes not listed default to DENY.
    The adapter enforces the mode before any request reaches the user.
    """
    mcp_servers: List[MCPServerEntry] = Field(default_factory=list)
    system_prompt_extension: Optional[str] = None
    permissions: Dict[ToolKind, PermissionMode] = Field(default_factory=dict)


class SpawnAgentPayload(BaseModel):
    """Backend → node: spawn agent process for a session.

    When acp_session_id is provided, gateway uses load_session instead of
    new_session — resuming the agent's persisted conversation.
    session_config carries intent-specific MCP servers, prompt, and capability flags.
    """
    payload_type: Literal["spawn_agent"] = "spawn_agent"
    session_id: str
    agent_id: str
    acp_session_id: Optional[str] = None  # resume: load existing ACP session
    session_config: Optional[SessionConfigPayload] = None


class StopAgentPayload(BaseModel):
    """Backend → node: stop agent process for a session."""
    payload_type: Literal["stop_agent"] = "stop_agent"
    session_id: str
    agent_id: str


class AgentSettings(BaseModel):
    """Explicit settings model — optional fields, extensible."""
    model: Optional[str] = None


class AgentLifecyclePayload(BaseModel):
    """Agent lifecycle event — gateway → backend."""
    payload_type: Literal["agent_lifecycle"] = "agent_lifecycle"
    session_id: Optional[str] = None
    acp_session_id: str = ""
    event: AgentLifecycleEvent
    agent_id: str = ""
    version: str = ""
    model_id: str = ""
    pid: int = 0
    return_code: int = 0
    available_models: List[str] = []


class ApplySettingsPayload(BaseModel):
    """Backend → node: apply settings (model switch) to an active session."""
    payload_type: Literal["apply_settings"] = "apply_settings"
    session_id: str
    settings: AgentSettings


class AgentSettingChangePayload(BaseModel):
    """Agent setting change confirmation — gateway → backend."""
    payload_type: Literal["agent_setting_change"] = "agent_setting_change"
    session_id: Optional[str] = None
    settings: AgentSettings


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
    SessionDeclaredPayload,
    SessionAcknowledgedPayload,
    ApplySettingsPayload,
    AgentLifecyclePayload,
    AgentSettingChangePayload,
    SpawnAgentPayload,
    StopAgentPayload,
]

PAYLOAD_DISCRIMINATOR = "payload_type"
