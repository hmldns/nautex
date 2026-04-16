"""Gateway domain models and shared contracts.

Three config layers:

1. SupportedAgentRegistration — static per-agent-type config derived from probe matrix.
   How to launch, auth, env handling, ACP quirks. One per agent binary.

2. AgentConfig — per-session runtime config from backend (MDS-11).
   Permissions, model, tools, credentials, directory scope. Agent-agnostic.

3. RuntimeCapabilities — dynamic, populated from ACP session/new response.
   Available models, modes, actual capabilities. Discovered at runtime.

Reference: MDS-7, MDS-9, MDS-10, MDS-11, FILE
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, SecretStr


# ---------------------------------------------------------------------------
# Layer 1: Agent Registration (static, describes the binary itself)
# Pure binary description — does NOT contain environment or policy config.
# ---------------------------------------------------------------------------

class CredentialSource(str, Enum):
    """How the agent binary natively receives credentials."""
    ACP_AUTH = "acp_auth"       # via ACP authenticate method (Gemini, Cursor, Droid, Codex)
    ENV_VAR = "env_var"         # reads API key from environment (Claude Code, Goose)
    INTERNAL = "internal"       # agent manages own credentials (OpenCode, Kiro)


class SupportedAgentRegistration(BaseModel):
    """Describes an agent binary — what it IS, not how we use it.

    These are intrinsic properties of the binary that don't change
    across environments or sessions.
    """
    agent_id: str
    executable: str
    launch_args: List[str] = Field(default_factory=list)
    credential_source: CredentialSource = CredentialSource.ACP_AUTH


# ---------------------------------------------------------------------------
# Agent registrations — intrinsic binary descriptions from probe evidence
# ---------------------------------------------------------------------------

SUPPORTED_AGENTS: Dict[str, SupportedAgentRegistration] = {
    "gemini_cli": SupportedAgentRegistration(
        agent_id="gemini_cli",
        executable="gemini",
        launch_args=["--acp"],
        credential_source=CredentialSource.ACP_AUTH,
    ),
    "opencode": SupportedAgentRegistration(
        agent_id="opencode",
        executable="opencode",
        launch_args=["acp"],
        credential_source=CredentialSource.INTERNAL,
    ),
    "cursor_agent": SupportedAgentRegistration(
        agent_id="cursor_agent",
        executable="cursor-agent",
        launch_args=["acp"],
        credential_source=CredentialSource.ACP_AUTH,
    ),
    "claude_code": SupportedAgentRegistration(
        agent_id="claude_code",
        executable="claude-agent-acp",
        launch_args=[],
        credential_source=CredentialSource.ENV_VAR,
    ),
    "droid": SupportedAgentRegistration(
        agent_id="droid",
        executable="droid",
        launch_args=["exec", "--output-format", "acp"],
        credential_source=CredentialSource.ACP_AUTH,
    ),
    "codex": SupportedAgentRegistration(
        agent_id="codex",
        executable="codex-acp",
        launch_args=[],
        credential_source=CredentialSource.ACP_AUTH,
    ),
    "goose": SupportedAgentRegistration(
        agent_id="goose",
        executable="goose",
        launch_args=["acp", "--with-builtin", "developer"],
        credential_source=CredentialSource.ENV_VAR,
    ),
    "kiro_cli": SupportedAgentRegistration(
        agent_id="kiro_cli",
        executable="kiro-cli",
        launch_args=["acp"],
        credential_source=CredentialSource.INTERNAL,
    ),
    "mock_testing_agent": SupportedAgentRegistration(
        agent_id="mock_testing_agent",
        executable="<built-in>",
        launch_args=[],
        credential_source=CredentialSource.INTERNAL,
    ),
}


# ---------------------------------------------------------------------------
# Layer 2: Agent Session Config (per-session, from caller)
# ---------------------------------------------------------------------------

class MCPServerConfig(BaseModel):
    """MCP server to inject into agent session. Reference: MDS-9"""
    server_id: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)


class AgentSessionConfig(BaseModel):
    """Per-session configuration for launching and constraining an agent.

    Generic flags that the adapter interprets based on what it knows
    about the specific binary. The caller doesn't need to know
    agent-specific details — the adapter translates.

    Examples:
    - allow_file_read=True, allow_file_write=False → agent can read but not modify
    - allow_terminal=False → adapter denies all terminal permission requests
    - model="fast" → adapter resolves to agent-specific fast model
    """
    # What the agent should do
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    directory_scope: str

    # Granular capability flags — adapter enforces via permission gating
    allow_file_read: bool = True
    allow_file_write: bool = False
    allow_terminal: bool = False
    allow_mcp_tools: bool = True
    auto_approve_all: bool = False

    # Tool filtering — not yet wired; no ACP-level counterpart exists.
    # Enforcement point: permission request callback in adapter, matching
    # PermissionRequestPayload.tool_name against these lists.
    # tools_allowed: List[str] = Field(default_factory=list)
    # tools_denied: List[str] = Field(default_factory=list)

    # MCP servers to inject
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)

    # Credentials to inject into subprocess environment
    credentials: Dict[str, SecretStr] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 3: Runtime Capabilities (dynamic, from ACP session/new)
# ---------------------------------------------------------------------------

class PromptCapabilities(BaseModel):
    """Input modalities the agent supports — discovered at runtime."""
    image: bool = False
    audio: bool = False
    embedded_context: bool = False


class AgentCapabilities(BaseModel):
    """Functional capabilities — discovered from ACP initialize response."""
    load_session: bool = False
    prompt_capabilities: PromptCapabilities = Field(
        default_factory=PromptCapabilities
    )


class ModelInfo(BaseModel):
    """A model available through an agent — discovered from session/new."""
    id: str
    name: str
    provider: str = ""
    default: bool = False


class AgentDescriptor(BaseModel):
    """Agent identity and capabilities — populated from ACP responses.

    This is NOT hardcoded per adapter. It is built from:
    - agentInfo from initialize response (name, version)
    - agentCapabilities from initialize response
    - models from session/new response
    """
    agent_id: str
    name: str = ""
    version: str = ""
    executable: str = ""
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    available_models: List[ModelInfo] = Field(default_factory=list)
    current_model: Optional[str] = None


# ---------------------------------------------------------------------------
# Session and prompt domain types
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


# Shared protocol types — canonical definitions live in gateway.protocol/
# Re-exported here for backwards compatibility
from .protocol.payloads import ConsolidatedSessionUpdate, PermissionRequestPayload, PermissionResponsePayload
from .protocol.envelope import GatewayWsEnvelope
