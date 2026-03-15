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
    CancelSessionPayload,
    ExecutePromptPayload,
    GatewayPayload,
    HeartbeatPayload,
    PermissionRequestPayload,
    PermissionResponsePayload,
    SearchRequestPayload,
    SearchResponsePayload,
    SearchResultItem,
    SessionUpdatePayload,
    TelemetryPayload,
    ToolCallDetail,
)
from .routes import (
    FRONTEND_CANCEL_SESSION,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    FRONTEND_SEARCH_REQUEST,
    UTILITY_HEARTBEAT,
    UTILITY_PERMISSION_REQUEST,
    UTILITY_SESSION_UPDATE,
    UTILITY_TELEMETRY,
)
from .session_updates import ConsolidatedSessionUpdate
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
    "HeartbeatPayload",
    "PermissionRequestPayload",
    "PermissionResponsePayload",
    "SessionUpdatePayload",
    "TelemetryPayload",
    "ExecutePromptPayload",
    "CancelSessionPayload",
    "SearchRequestPayload",
    "SearchResponsePayload",
    "SearchResultItem",
    "ToolCallDetail",
    # Domain
    "ConsolidatedSessionUpdate",
    "NodeHeartbeatPayload",
    "EphemeralSessionTelemetry",
    # Routes
    "UTILITY_HEARTBEAT",
    "UTILITY_PERMISSION_REQUEST",
    "UTILITY_SESSION_UPDATE",
    "UTILITY_TELEMETRY",
    "FRONTEND_PERMISSION_RESPONSE",
    "FRONTEND_EXECUTE_PROMPT",
    "FRONTEND_CANCEL_SESSION",
    "FRONTEND_SEARCH_REQUEST",
]
