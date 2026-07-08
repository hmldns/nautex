#!/usr/bin/env python3
"""Hermes ACP probe.

Binary: hermes-acp (entry point shipped by `hermes-agent[acp]` extra)
Transport: stdio
Auth: inherits from ~/.hermes/config.yaml / ~/.hermes/.env (no ACP auth methods)

Install (manual, one of):
    pip install --upgrade 'hermes-agent[acp]'      # if hermes-agent is pip-installed
    pipx install 'hermes-agent[acp]'                # isolated venv
    uv tool install 'hermes-agent[acp]'             # uv-managed tool
    uvx --from 'hermes-agent[acp]' hermes-acp       # zero-install ephemeral run
    pip install -e '.[acp]'                         # from a local hermes-agent checkout

Reference: https://hermes-agent.nousresearch.com/docs/user-guide/features/acp

This probe additionally injects an MCP server to exercise Hermes's MCP routing
surface — useful for inspecting how Hermes stamps MCP-originated tool_call
metadata (look for `_meta` fields and unusual `tool_call.kind` values).
"""

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from harness import (
    C, ProbeClient, log,
    phase_initialize, phase_authenticate, phase_session,
    phase_set_model, phase_prompt,
    show_workspace, show_stats, show_consolidated, run_with_timeout,
    DEFAULT_PROMPT,
    setup_workspace, cleanup_workspace, add_common_args,
)
from acp import spawn_agent_process
from acp.schema import McpServerStdio


CMD = "hermes-acp"
ARGS = []
DEFAULT_MODEL = None


AGENT_ID = "hermes"


def _sample_mcp_servers():
    """A tiny stdio MCP server so we can watch how Hermes surfaces MCP tool calls.

    Uses `uvx mcp-server-fetch` — a public reference MCP server that fetches
    URLs. Picked because it (a) installs on demand via uvx, (b) exposes a
    single recognizable tool, (c) doesn't need credentials. If uvx is not on
    PATH or first-run package fetch is slow, the session/new call will simply
    take longer; an empty list is a safe fallback.
    """
    if not shutil.which("uvx"):
        log("mcp", C.YELLOW, "uvx not found — skipping MCP injection")
        return []
    return [
        McpServerStdio(
            name="fetch",
            command="uvx",
            args=["mcp-server-fetch"],
            env=[],
        )
    ]


async def run(prompt: str, model: str | None, timeout: int, workspace: str | None = None, keep: bool = False, consolidate: bool = False, with_mcp: bool = True):
    if not shutil.which(CMD):
        print(f"{C.RED}'{CMD}' not found in PATH{C.RESET}")
        print(f"{C.DIM}Install with one of:{C.RESET}")
        print(f"  pipx install 'hermes-agent[acp]'")
        print(f"  uv tool install 'hermes-agent[acp]'")
        print(f"  uvx --from 'hermes-agent[acp]' hermes-acp   # ephemeral")
        sys.exit(1)

    tmpdir, should_cleanup = setup_workspace(AGENT_ID, workspace, keep)
    client = ProbeClient(consolidate=consolidate)

    print(f"{C.BOLD}=== Probe: Hermes ==={C.RESET}")
    print(f"  Binary:    {shutil.which(CMD)}")
    print(f"  Workspace: {tmpdir}")
    print(f"  Timeout:   {timeout}s")
    print(f"  MCP inj:   {'on (fetch via uvx)' if with_mcp else 'off'}")
    print()

    try:
        async with spawn_agent_process(client, CMD, *ARGS, cwd=tmpdir) as (conn, proc):
            log("spawn", C.GREEN, f"PID {proc.pid}")

            try:
                init = await phase_initialize(conn, timeout=20)
            except asyncio.TimeoutError:
                log("init", C.RED, "TIMEOUT")
                return
            except Exception as e:
                log("init", C.RED, f"FAILED: {e}")
                return

            info = getattr(init, "agent_info", None)
            if info:
                log("agent", C.CYAN, f"{getattr(info, 'name', '?')} v{getattr(info, 'version', '?')}")
            else:
                log("agent", C.YELLOW, "no agentInfo returned")
            caps = getattr(init, "agent_capabilities", None)
            if caps:
                pc = getattr(caps, "prompt_capabilities", None)
                log("caps", C.DIM, f"loadSession={caps.load_session} image={pc and pc.image} audio={pc and pc.audio} embeddedContext={pc and pc.embedded_context}")

            auth_methods = getattr(init, "auth_methods", []) or []
            if auth_methods:
                log("auth", C.DIM, f"methods: {[am.id for am in auth_methods]}")
                try:
                    await phase_authenticate(conn, init)
                except Exception as e:
                    log("auth", C.YELLOW, f"auth failed: {e} — continuing without")
            else:
                log("auth", C.DIM, "no auth methods (uses ~/.hermes/config.yaml)")

            mcp_servers = _sample_mcp_servers() if with_mcp else []

            try:
                session = await phase_session(conn, tmpdir, mcp_servers=mcp_servers, timeout=45)
            except Exception as e:
                log("session", C.RED, f"FAILED: {e}")
                return

            target = model or DEFAULT_MODEL
            if target:
                await phase_set_model(conn, session.session_id, target)

            await phase_prompt(conn, session.session_id, prompt, timeout=timeout - 30)

            show_workspace(tmpdir)
            show_stats(client)
            show_consolidated(client)

            print(f"\n{C.BOLD}--- Execution Model ---{C.RESET}")
            if client.stats.fs_writes > 0 or client.stats.terminal_creates > 0:
                print(f"  {C.CYAN}DELEGATED{C.RESET}")
            elif client.stats.permissions_requested > 0:
                print(f"  {C.YELLOW}LOCAL + PERMISSION GATING{C.RESET}")
            else:
                print(f"  {C.YELLOW}LOCAL — no client calls observed{C.RESET}")
    finally:
        cleanup_workspace(tmpdir, should_cleanup)


def main():
    parser = argparse.ArgumentParser(description="Hermes ACP probe")
    add_common_args(parser)
    parser.add_argument("--no-mcp", action="store_true", help="Skip MCP server injection")
    args = parser.parse_args()

    asyncio.run(run_with_timeout(
        run(args.prompt, args.model, args.timeout, workspace=args.workspace, keep=args.keep, consolidate=args.consolidate, with_mcp=not args.no_mcp),
        timeout=args.timeout,
        agent_id="hermes",
    ))


if __name__ == "__main__":
    main()
