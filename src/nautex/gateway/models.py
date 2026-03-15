"""Gateway domain models and shared contracts.

Defines the Pydantic models used across the adapter boundary.
Domain types referenced by AgentAdapter are defined here so that
the typing contract is enforceable by mypy.

Reference: MDS-7, MDS-9, MDS-11, FILE
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, SecretStr


# ---------------------------------------------------------------------------
# Agent configuration models (MDS-7, MDS-9, MDS-11)
# ---------------------------------------------------------------------------

class PermissionConfig(BaseModel):
    """Permission settings for agent execution. Reference: MDS-7"""
    auto_approve_all: bool = False
    read_only: bool = True


class MCPServerConfig(BaseModel):
    """MCP server configuration passed to an agent. Reference: MDS-9"""
    server_id: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Universal configuration passed to any agent. Reference: MDS-11"""
    system_prompt: Optional[str] = None
    tools_allowed: List[str] = Field(default_factory=list)
    tools_denied: List[str] = Field(default_factory=list)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    model: Optional[str] = None
    directory_scope: str
    credentials: Dict[str, SecretStr] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent descriptor (static metadata)
# ---------------------------------------------------------------------------

class PromptCapabilities(BaseModel):
    """What input modalities the agent supports."""
    image: bool = False
    audio: bool = False
    embedded_context: bool = False


class AgentCapabilities(BaseModel):
    """Functional capabilities of an agent."""
    load_session: bool = False
    prompt_capabilities: PromptCapabilities = Field(
        default_factory=PromptCapabilities
    )


class ModelInfo(BaseModel):
    """A model available through an agent."""
    id: str
    name: str
    provider: str = ""
    default: bool = False


class AgentDescriptor(BaseModel):
    """Static metadata describing an agent binary."""
    agent_id: str
    name: str
    version: str
    executable: str
    agent_type: str
    acp_supported: bool = True
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    supported_models: List[ModelInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Session and prompt domain types (stubs for typing contract)
# Full implementations will be expanded as upstream specs are realized.
# ---------------------------------------------------------------------------

class GatewaySessionConfig(BaseModel):
    """Parameters for creating a new agent session."""
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PromptContent(BaseModel):
    """Normalized prompt input passed to an agent."""
    text: str
    attachments: List[Any] = Field(default_factory=list)


class PromptResponse(BaseModel):
    """Full response from a blocking prompt execution."""
    prompt_id: str
    stop_reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConsolidatedSessionUpdate(BaseModel):
    """Semantic batched update from an agent stream.

    This is the strict public boundary type — adapters MUST yield only
    this type, never raw JSON dicts. Reference: MDS-35
    """
    kind: str
    data: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class PermissionRequestPayload(BaseModel):
    """Tool permission gate request from the agent."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""


class PermissionResponsePayload(BaseModel):
    """User's approve/deny response to a permission request."""
    request_id: str
    approved: bool
