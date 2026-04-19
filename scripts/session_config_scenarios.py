"""Scenarios for the session-config probe.

Each scenario defines:
- how to build an `AgentSessionConfig` (policy, MCP, prompt extension)
- a prompt sequence to send
- a permission-request decision function
- a post-run `check` that produces Assertion rows

Scenarios live here so the runner stays generic. Add new cases by appending
to ALL_SCENARIOS at the bottom.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Set

from nautex.gateway.models import AgentSessionConfig, MCPServerConfig
from nautex.gateway.protocol import (
    PermissionAction,
    PermissionRequestPayload,
    PermissionResponsePayload,
)
from nautex.gateway.protocol.enums import PermissionMode, SessionUpdateKind, ToolKind


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseContext:
    """Everything a scenario's `check` may inspect post-run."""
    agent_id: str
    scenario_id: str
    workdir: Path
    config: AgentSessionConfig
    csus: List[dict]            # serialized ConsolidatedSessionUpdate dumps
    permissions: List[dict]     # [{request: {...}, response: {...}}]
    stdout_text: str            # concatenated AGENT_MESSAGE text
    fs_diff: dict               # {"created": [...], "modified": [...], "deleted": [...]}
    stop_reasons: List[str]     # per prompt
    duration_ms: int


PermissionDecider = Callable[[PermissionRequestPayload], PermissionResponsePayload]
Checker = Callable[[CaseContext], List[Assertion]]


@dataclass
class Scenario:
    id: str
    description: str
    build_config: Callable[[Path], AgentSessionConfig]
    prompts: List[str]
    on_permission: PermissionDecider
    check: Checker
    skip_for: Set[str] = field(default_factory=set)
    env_gate: Optional[str] = None


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _respond(prp: PermissionRequestPayload, action: PermissionAction) -> PermissionResponsePayload:
    return PermissionResponsePayload(
        permission_id=prp.permission_id,
        acp_session_id=prp.acp_session_id,
        action=action,
    )


def policy_honoring(prp: PermissionRequestPayload) -> PermissionResponsePayload:
    """Default probe permission handler.

    Mirrors what the backend does in production: if the adapter wrapper
    already stamped `prp.policy_action` (because the session config dictated
    the outcome), honor it. Otherwise (ASK/DEFAULT reaching the callback),
    approve — so `approval_flow` scenarios can override with `always_deny`.
    """
    if prp.policy_action is not None:
        return _respond(prp, prp.policy_action)
    return _respond(prp, PermissionAction.APPROVE)


def always_approve(prp: PermissionRequestPayload) -> PermissionResponsePayload:
    return _respond(prp, PermissionAction.APPROVE)


def always_deny(prp: PermissionRequestPayload) -> PermissionResponsePayload:
    return _respond(prp, PermissionAction.DENY)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _files_created_under_workdir(ctx: CaseContext) -> List[str]:
    return list(ctx.fs_diff.get("created", [])) + list(ctx.fs_diff.get("modified", []))


def _stop_reason_ok(ctx: CaseContext) -> bool:
    """end_turn is the clean terminal state; refusal is also benign (we emit
    it when we surface an AGENT_ERROR). Anything else is surprising."""
    return all(r in ("end_turn", "refusal") for r in ctx.stop_reasons)


def _has_csu_kind(ctx: CaseContext, kind: SessionUpdateKind) -> bool:
    return any(c.get("kind") == kind.value for c in ctx.csus)


def _denied_permissions(ctx: CaseContext) -> List[dict]:
    return [
        p for p in ctx.permissions
        if p.get("response", {}).get("action") == PermissionAction.DENY.value
    ]


# Agents known to not delegate permission requests over ACP at all — their
# enforcement (or lack thereof) is visible only through config files and
# side-effects, not through the `on_permission_request` callback.
_NO_ACP_PERMISSION_AGENTS: Set[str] = {"opencode"}


# ---------------------------------------------------------------------------
# Config builders
# ---------------------------------------------------------------------------


def _cfg(workdir: Path, **kwargs: Any) -> AgentSessionConfig:
    return AgentSessionConfig(directory_scope=str(workdir), **kwargs)


def cfg_default(workdir: Path) -> AgentSessionConfig:
    return _cfg(workdir)


def cfg_read_only(workdir: Path) -> AgentSessionConfig:
    return _cfg(
        workdir,
        permissions={
            ToolKind.READ: PermissionMode.ALLOW,
            ToolKind.SEARCH: PermissionMode.ALLOW,
            ToolKind.EDIT: PermissionMode.DENY,
            ToolKind.EXECUTE: PermissionMode.DENY,
        },
    )


def cfg_deny_write(workdir: Path) -> AgentSessionConfig:
    return _cfg(
        workdir,
        permissions={
            ToolKind.READ: PermissionMode.ALLOW,
            ToolKind.SEARCH: PermissionMode.ALLOW,
            ToolKind.EDIT: PermissionMode.DENY,
            ToolKind.EXECUTE: PermissionMode.ALLOW,
        },
    )


MARKER = "PROBE-MARKER-4712"


def cfg_system_prompt(workdir: Path) -> AgentSessionConfig:
    return _cfg(
        workdir,
        permissions={k: PermissionMode.ALLOW for k in ToolKind},
        system_prompt_extension=(
            "You are participating in an automated session-config probe. "
            f"Begin your reply with the exact marker {MARKER} on its own line. "
            "Then reply normally."
        ),
    )


def cfg_mcp_injection(workdir: Path) -> AgentSessionConfig:
    return _cfg(
        workdir,
        permissions={k: PermissionMode.ALLOW for k in ToolKind},
        mcp_servers=[
            MCPServerConfig(server_id="nautex", command="uvx", args=["nautex", "mcp"])
        ],
    )


def cfg_approval_flow(workdir: Path) -> AgentSessionConfig:
    return _cfg(
        workdir,
        permissions={
            ToolKind.READ: PermissionMode.ALLOW,
            ToolKind.SEARCH: PermissionMode.ALLOW,
            ToolKind.EDIT: PermissionMode.ASK,
            ToolKind.EXECUTE: PermissionMode.ASK,
        },
    )


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------


def check_default_noop(ctx: CaseContext) -> List[Assertion]:
    return [
        Assertion("turn_ended_cleanly", _stop_reason_ok(ctx),
                  f"stop_reasons={ctx.stop_reasons}"),
        Assertion("agent_produced_text", bool(ctx.stdout_text.strip()),
                  f"stdout length={len(ctx.stdout_text)}"),
    ]


def check_read_only_exploration(ctx: CaseContext) -> List[Assertion]:
    created = _files_created_under_workdir(ctx)
    return [
        Assertion("no_files_written", not created,
                  f"created/modified={created}"),
        Assertion("turn_ended_cleanly", _stop_reason_ok(ctx),
                  f"stop_reasons={ctx.stop_reasons}"),
    ]


def check_deny_write(ctx: CaseContext) -> List[Assertion]:
    created = _files_created_under_workdir(ctx)
    denied = _denied_permissions(ctx)
    # Agents that don't delegate permission via ACP (OpenCode) show enforcement
    # purely via config-level tool restriction + fs_diff, not via denied perms.
    return [
        Assertion("no_files_written", not created, f"created/modified={created}"),
        Assertion("denials_or_no_attempts",
                  bool(denied) or ctx.agent_id in _NO_ACP_PERMISSION_AGENTS,
                  f"denied_permissions={len(denied)}"),
        Assertion("turn_ended_cleanly", _stop_reason_ok(ctx),
                  f"stop_reasons={ctx.stop_reasons}"),
    ]


def check_deny_all_writes_and_exec(ctx: CaseContext) -> List[Assertion]:
    created = _files_created_under_workdir(ctx)
    return [
        Assertion("no_files_written", not created, f"created/modified={created}"),
        Assertion("turn_ended_cleanly", _stop_reason_ok(ctx),
                  f"stop_reasons={ctx.stop_reasons}"),
    ]


def check_system_prompt_marker(ctx: CaseContext) -> List[Assertion]:
    found = MARKER.lower() in ctx.stdout_text.lower()
    return [
        Assertion("marker_in_reply", found,
                  f"marker={'present' if found else 'absent'}; stdout_len={len(ctx.stdout_text)}"),
    ]


def check_mcp_injection(ctx: CaseContext) -> List[Assertion]:
    lowered = ctx.stdout_text.lower()
    csu_refs_mcp = any("mcp__nautex" in (c.get("text") or "").lower() for c in ctx.csus)
    text_refs_mcp = "nautex" in lowered and ("mcp" in lowered or "tool" in lowered)
    return [
        Assertion("nautex_mcp_referenced", csu_refs_mcp or text_refs_mcp,
                  f"csu_refs={csu_refs_mcp} text_refs={text_refs_mcp}"),
    ]


def check_approval_flow(ctx: CaseContext) -> List[Assertion]:
    requested = bool(ctx.permissions) or ctx.agent_id in _NO_ACP_PERMISSION_AGENTS
    created = _files_created_under_workdir(ctx)
    return [
        Assertion("permission_requested_or_na", requested,
                  f"permissions={len(ctx.permissions)}"),
        Assertion("no_files_written", not created, f"created/modified={created}"),
    ]


def check_rate_limit_capture(ctx: CaseContext) -> List[Assertion]:
    errors = [c for c in ctx.csus if c.get("kind") == SessionUpdateKind.AGENT_ERROR.value]
    return [
        Assertion("agent_error_csu_present", bool(errors),
                  f"agent_error_count={len(errors)}"),
        Assertion("error_has_code", any(e.get("error_code") for e in errors),
                  "at least one AGENT_ERROR carries a numeric JSON-RPC code"),
    ]


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------


ALL_SCENARIOS: List[Scenario] = [
    Scenario(
        id="default_noop",
        description="No config overrides; sanity check that the adapter round-trips a prompt.",
        build_config=cfg_default,
        prompts=["Say hi in one short sentence."],
        on_permission=policy_honoring,
        check=check_default_noop,
    ),
    Scenario(
        id="read_only_exploration",
        description="READ/SEARCH allow, EDIT/EXEC deny — classic exploration mode.",
        build_config=cfg_read_only,
        prompts=["List the files in the current directory."],
        on_permission=policy_honoring,
        check=check_read_only_exploration,
    ),
    Scenario(
        id="deny_write",
        description="EDIT denied, other scopes allowed; must not produce files via Edit/Write.",
        build_config=cfg_deny_write,
        prompts=[
            "Use your Write/edit tool to create probe-test.txt with content 'hi'. "
            "Just attempt it once."
        ],
        on_permission=policy_honoring,
        check=check_deny_write,
    ),
    Scenario(
        id="deny_all_writes_and_exec",
        description="EDIT+EXEC denied; no file should be produced even via shell fallback.",
        build_config=cfg_read_only,
        prompts=[
            "Try to create a file named deny-all.txt with content 'x' using any tool you have. "
            "If any attempt is blocked, narrate briefly and stop."
        ],
        on_permission=policy_honoring,
        check=check_deny_all_writes_and_exec,
    ),
    Scenario(
        id="system_prompt_marker",
        description="Verifies system_prompt_extension reaches the agent (via config OR first-turn prepend).",
        build_config=cfg_system_prompt,
        prompts=["Reply with anything."],
        on_permission=policy_honoring,
        check=check_system_prompt_marker,
    ),
    Scenario(
        id="mcp_injection",
        description="Nautex MCP server declared in config; agent should see it in its tool list.",
        build_config=cfg_mcp_injection,
        prompts=["List the MCP servers and tools available to you right now."],
        on_permission=policy_honoring,
        check=check_mcp_injection,
    ),
    Scenario(
        id="approval_flow",
        description="EDIT set to ASK; probe responds DENY; permission event must surface in ACP.",
        build_config=cfg_approval_flow,
        prompts=["Create approve-test.txt with content 'x'."],
        on_permission=always_deny,
        check=check_approval_flow,
        skip_for=_NO_ACP_PERMISSION_AGENTS,
    ),
    Scenario(
        id="rate_limit_capture",
        description="Captures AGENT_ERROR CSU shape; enable with PROBE_FORCE_RATELIMIT=1.",
        build_config=cfg_default,
        prompts=["Say hi."],
        on_permission=policy_honoring,
        check=check_rate_limit_capture,
        env_gate="PROBE_FORCE_RATELIMIT",
    ),
]


SCENARIOS_BY_ID = {s.id: s for s in ALL_SCENARIOS}


def scenario_is_enabled(sc: Scenario) -> bool:
    if sc.env_gate is None:
        return True
    return bool(os.environ.get(sc.env_gate))
