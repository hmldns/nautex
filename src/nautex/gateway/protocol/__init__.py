"""Shared protocol types between nautex-oss-util and nt-backend.

This package can be copy-pasted between repos to keep types in sync.
Only pydantic BaseModel types, enums, and string constants — no business logic.
"""

from .enums import (
    NodeStatus,
    PermissionAction,
    SessionUpdateKind,
    ToolCallStatus,
    ToolKind,
)
from .envelope import GatewayWsEnvelope
from .payloads import (
    PAYLOAD_DISCRIMINATOR,
    AgentDescriptorPayload,
    CancelSessionPayload,
    ConsolidatedSessionUpdate,
    EnvironmentDescriptor,
    ExecutePromptPayload,
    GatewayPayload,
    HeartbeatPayload,
    NodeRegistrationPayload,
    PermissionRequestPayload,
    PermissionResponsePayload,
    RegistrationAckPayload,
    SearchRequestPayload,
    SearchResponsePayload,
    SearchResultItem,
    TelemetryPayload,
)
from .routes import (
    BACKEND_REGISTRATION_ACK,
    BACKEND_SESSION_ACKNOWLEDGED,
    FRONTEND_CANCEL_SESSION,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    FRONTEND_SEARCH_REQUEST,
    NODE_REGISTER,
    NODE_SESSION_DECLARED,
    NODE_HEARTBEAT,
    NODE_PERMISSION_REQUEST,
    NODE_SESSION_UPDATE,
    NODE_TELEMETRY,
)
from .telemetry import EphemeralSessionTelemetry, NodeHeartbeatPayload

__all__ = [
    # Enums
    "SessionUpdateKind",
    "ToolCallStatus",
    "ToolKind",
    "PermissionAction",
    "NodeStatus",
    # Envelope
    "GatewayWsEnvelope",
    "GatewayPayload",
    "PAYLOAD_DISCRIMINATOR",
    # Payloads
    "AgentDescriptorPayload",
    "EnvironmentDescriptor",
    "NodeRegistrationPayload",
    "HeartbeatPayload",
    "PermissionRequestPayload",
    "PermissionResponsePayload",
    "ConsolidatedSessionUpdate",
    "TelemetryPayload",
    "ExecutePromptPayload",
    "CancelSessionPayload",
    "SearchRequestPayload",
    "SearchResponsePayload",
    "RegistrationAckPayload",
    "SearchResultItem",
    # Telemetry
    "NodeHeartbeatPayload",
    "EphemeralSessionTelemetry",
    # Routes
    "NODE_REGISTER",
    "NODE_SESSION_DECLARED",
    "NODE_HEARTBEAT",
    "NODE_PERMISSION_REQUEST",
    "NODE_SESSION_UPDATE",
    "NODE_TELEMETRY",
    "BACKEND_REGISTRATION_ACK",
    "BACKEND_SESSION_ACKNOWLEDGED",
    "FRONTEND_PERMISSION_RESPONSE",
    "FRONTEND_EXECUTE_PROMPT",
    "FRONTEND_CANCEL_SESSION",
    "FRONTEND_SEARCH_REQUEST",
]
