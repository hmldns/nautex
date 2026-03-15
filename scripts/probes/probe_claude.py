#!/usr/bin/env python3
"""Claude Code ACP probe.

Binary: claude-agent-acp (Zed wrapper over Claude Agent SDK)
Transport: stdio
Auth: UNKNOWN — may use ANTHROPIC_API_KEY or cached creds
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
    show_workspace, show_stats, run_with_timeout,
    DEFAULT_PROMPT,
    setup_workspace, cleanup_workspace, add_common_args,
)
from acp import spawn_agent_process


CMD = "claude-agent-acp"
ARGS = []
DEFAULT_MODEL = None


AGENT_ID = "claude"


async def run(prompt: str, model: str | None, timeout: int, workspace: str | None = None, keep: bool = False):
    if not shutil.which(CMD):
        print(f"{C.RED}'{CMD}' not found in PATH{C.RESET}")
        sys.exit(1)

    tmpdir, should_cleanup = setup_workspace(AGENT_ID, workspace, keep)
    client = ProbeClient()

    print(f"{C.BOLD}=== Probe: Claude Code ==={C.RESET}")
    print(f"  Binary:    {shutil.which(CMD)}")
    print(f"  Workspace: {tmpdir}")
    print(f"  Timeout:   {timeout}s")
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
                log("auth", C.DIM, "no auth methods")

            try:
                session = await phase_session(conn, tmpdir)
            except Exception as e:
                log("session", C.RED, f"FAILED: {e}")
                return

            target = model or DEFAULT_MODEL
            if target:
                await phase_set_model(conn, session.session_id, target)

            await phase_prompt(conn, session.session_id, prompt, timeout=timeout - 30)

            show_workspace(tmpdir)
            show_stats(client)

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
    parser = argparse.ArgumentParser(description="Claude Code ACP probe")
    add_common_args(parser)
    args = parser.parse_args()

    asyncio.run(run_with_timeout(
        run(args.prompt, args.model, args.timeout, workspace=args.workspace, keep=args.keep),
        timeout=args.timeout,
        agent_id="claude_code",
    ))


if __name__ == "__main__":
    main()
