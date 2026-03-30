"""Telemetry payloads shared between gateway node and backend.

Two channels:
1. NodeHeartbeatPayload — 4Hz global daemon health over WS uplink
2. EphemeralSessionTelemetry — per-session metrics over WS
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .enums import NodeStatus


class NodeHeartbeatPayload(BaseModel):
    """Global node health payload flushed at 4Hz over WebSocket uplink."""
    node_instance_id: str
    active_sessions_count: int
    status: NodeStatus = NodeStatus.HEALTHY


class EphemeralSessionTelemetry(BaseModel):
    """Per-session ephemeral metrics streamed over WebSocket."""
    acp_session_id: str
    active_tool: Optional[str] = None
    processed_tokens_estimate: int
    is_typing: bool
