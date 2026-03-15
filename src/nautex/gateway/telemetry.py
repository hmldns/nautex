"""Gateway telemetry models for network heartbeat and session metrics.

Two distinct telemetry channels:

1. NodeHeartbeatPayload — 3Hz global daemon health pulse over WebSocket uplink.
   Lightweight: just instance ID, active session count, status string.

2. EphemeralSessionTelemetry — per-session metrics (typing, active tool, tokens).
   Streamed via WebRTC data channel (fallback: WebSocket) independently of heartbeat.

Reference: MDSNAUTX-25, MDSNAUTX-26
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class NodeHeartbeatPayload(BaseModel):
    """Global node health payload flushed at 3Hz over WebSocket uplink."""
    utility_instance_id: str
    active_sessions_count: int
    status: str = "healthy"


class EphemeralSessionTelemetry(BaseModel):
    """Per-session ephemeral metrics streamed via WebRTC (fallback WebSocket)."""
    session_id: str
    active_tool: Optional[str] = None
    processed_tokens_estimate: int
    is_typing: bool
