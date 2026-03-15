"""Gateway configuration management.

Two config domains:

1. GatewayNodeConfig — daemon-level settings (headless, logging, directory scope,
   ignored dirs). Reference: MDSNAUTX-10

2. Agent config resolution — registry lookup, binary validation, environment
   building, auth method selection. Reference: MDS-88
"""

from __future__ import annotations

import os
import shutil
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .models import (
    AgentCapabilities,
    AgentDescriptor,
    SupportedAgentRegistration,
    AgentSessionConfig,
    CredentialSource,
    ModelInfo,
    PromptCapabilities,
    SUPPORTED_AGENTS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gateway Node Config (MDSNAUTX-10)
# ---------------------------------------------------------------------------

class GatewayNodeConfig(BaseModel):
    """Daemon execution parameters.

    Controls headless behavior, privacy gating, directory scoping,
    and ignored directory defaults for subprocesses and the indexer.
    Reference: MDSNAUTX-10
    """
    headless_mode: bool = False
    auto_approve_privacy_gate: bool = False
    log_level: str = "INFO"
    directory_scope: str = Field(description="Strict CWD for all subprocesses and the Indexer")
    ignored_directories: List[str] = Field(
        default_factory=lambda: [".git", "node_modules", ".next", "__pycache__", "venv", ".venv"]
    )
    uplink_url: Optional[str] = None
    auth_token: Optional[str] = None
    utility_instance_id: str = ""


# ---------------------------------------------------------------------------
# Agent config resolution (MDS-88)
# ---------------------------------------------------------------------------

class AgentNotFoundError(Exception):
    """Raised when an agent_id is not in the registry."""
    pass


class AgentBinaryNotFoundError(Exception):
    """Raised when the agent binary is not installed on the host."""
    pass


def get_registration(agent_id: str) -> SupportedAgentRegistration:
    """Look up agent registration from the registry.

    Raises AgentNotFoundError if not registered.
    """
    reg = SUPPORTED_AGENTS.get(agent_id)
    if not reg:
        available = ", ".join(SUPPORTED_AGENTS.keys())
        raise AgentNotFoundError(
            f"Agent '{agent_id}' not registered. Available: {available}"
        )
    return reg


def validate_binary(reg: SupportedAgentRegistration) -> str:
    """Check that the agent binary is installed. Returns full path.

    Raises AgentBinaryNotFoundError if not found in PATH.
    """
    path = shutil.which(reg.executable)
    if not path:
        raise AgentBinaryNotFoundError(
            f"Binary '{reg.executable}' for agent '{reg.agent_id}' not found in PATH"
        )
    return path


# Default env keys to strip — security policy for credential sandboxing
DEFAULT_STRIP_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"]


def build_env(
    reg: SupportedAgentRegistration,
    session_config: AgentSessionConfig,
) -> Dict[str, str]:
    """Build the environment dict for spawning the agent subprocess.

    Uses the registration's credential_source to determine env handling:
    - ENV_VAR agents need the full host env (their keys live there)
    - ACP_AUTH/INTERNAL agents get stripped env (keys removed)
    - Session credentials are always injected
    """
    env = dict(os.environ)

    # Agents that read credentials from env need full env passed through.
    # Others get sensitive keys stripped for sandboxing.
    if reg.credential_source != CredentialSource.ENV_VAR:
        for key in DEFAULT_STRIP_KEYS:
            env.pop(key, None)

    # Inject session-level credentials
    for key, secret in session_config.credentials.items():
        env[key] = secret.get_secret_value()

    return env


def build_launch_command(
    reg: SupportedAgentRegistration,
    session_config: AgentSessionConfig,
) -> List[str]:
    """Build the full command to spawn the agent."""
    return [reg.executable] + list(reg.launch_args)


def resolve_auth_method(
    reg: SupportedAgentRegistration,
    acp_auth_methods: List[Dict[str, Any]],
) -> Optional[str]:
    """Select the best auth method from ACP init response.

    Agents with credential_source != ACP_AUTH don't need ACP auth.
    For ACP_AUTH agents, picks first oauth/login method, then first available.

    Returns None if no auth needed or no methods available.
    """
    if not acp_auth_methods:
        return None

    if reg.credential_source != CredentialSource.ACP_AUTH:
        return None

    def _get_id(am: Any) -> str:
        if isinstance(am, dict):
            return str(am.get("id", ""))
        return str(getattr(am, "id", ""))

    # Prefer oauth/login pattern
    for am in acp_auth_methods:
        am_id = _get_id(am)
        if "oauth" in am_id or "login" in am_id:
            return am_id

    # First available
    return _get_id(acp_auth_methods[0])


def list_available_agents() -> Dict[str, Dict[str, Any]]:
    """List all registered agents with their install status.

    Returns dict of agent_id → {registration, installed, binary_path}.
    """
    result = {}
    for agent_id, reg in SUPPORTED_AGENTS.items():
        path = shutil.which(reg.executable)
        result[agent_id] = {
            "registration": reg,
            "installed": path is not None,
            "binary_path": path,
        }
    return result


# ---------------------------------------------------------------------------
# Dynamic capabilities — populated from ACP runtime responses
# ---------------------------------------------------------------------------

def build_descriptor_from_init(
    reg: SupportedAgentRegistration,
    init_result: Any,
) -> AgentDescriptor:
    """Build AgentDescriptor from ACP initialize response.

    Extracts agentInfo and agentCapabilities from the SDK's InitializeResponse.
    Falls back to registration defaults for missing fields.
    """
    descriptor = AgentDescriptor(
        agent_id=reg.agent_id,
        executable=reg.executable,
    )

    # agentInfo — some agents don't return this (Cursor, Goose)
    info = getattr(init_result, "agent_info", None)
    if info:
        descriptor.name = getattr(info, "name", "") or ""
        descriptor.version = getattr(info, "version", "") or ""

    # agentCapabilities
    caps = getattr(init_result, "agent_capabilities", None)
    if caps:
        pc = getattr(caps, "prompt_capabilities", None)
        descriptor.capabilities = AgentCapabilities(
            load_session=getattr(caps, "load_session", False) or False,
            prompt_capabilities=PromptCapabilities(
                image=getattr(pc, "image", False) if pc else False,
                audio=getattr(pc, "audio", False) if pc else False,
                embedded_context=getattr(pc, "embedded_context", False) if pc else False,
            ),
        )

    return descriptor


def update_descriptor_from_session(
    descriptor: AgentDescriptor,
    session_result: Any,
) -> AgentDescriptor:
    """Update AgentDescriptor with models from ACP session/new response.

    Extracts available models and current model from the session response.
    """
    models_info = getattr(session_result, "models", None)
    if not models_info:
        return descriptor

    available = getattr(models_info, "available_models", None) or []
    current_id = getattr(models_info, "current_model_id", None)

    model_list = []
    for m in available:
        model_id = getattr(m, "model_id", "") or ""
        name = getattr(m, "name", model_id) or model_id
        model_list.append(ModelInfo(
            id=model_id,
            name=name,
            default=(model_id == current_id),
        ))

    descriptor.available_models = model_list
    descriptor.current_model = current_id
    return descriptor
