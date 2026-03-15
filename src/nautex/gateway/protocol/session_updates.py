"""Consolidated session update shared between utility and backend.

The strict public boundary type — adapters yield only this.
Backend receives these over WebSocket for UI rendering and persistence.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from .enums import SessionUpdateKind, ToolCallStatus, ToolKind


class ConsolidatedSessionUpdate(BaseModel):
    """Semantic batched update from an agent stream.

    Strict public boundary type — adapters yield only this, never raw dicts.
    Reference: MDS-35
    """
    kind: SessionUpdateKind
    session_id: Optional[str] = None
    text: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_title: Optional[str] = None
    tool_status: Optional[ToolCallStatus] = None
    tool_kind: Optional[ToolKind] = None
    mode_id: Optional[str] = None
    commands_count: Optional[int] = None
    usage_size: Optional[int] = None
    usage_used: Optional[int] = None
