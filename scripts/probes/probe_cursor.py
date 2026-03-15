#!/usr/bin/env python3
"""Cursor Agent ACP probe.

Known from prior initialize-only probe:
- Auth: cursor_login (uses cached Cursor creds from `cursor-agent login`)
- embeddedContext: false
- Execution model: UNKNOWN — suspected local (Cursor forum says it ignores client fs caps)

This probe will discover:
- Does Cursor delegate fs/terminal or execute locally?
- What permission gate behavior does it use?
- What session update types does it emit?
- Does it support set_session_model?
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


CMD = "cursor-agent"
ARGS = ["acp"]
AUTH_PREFER = "cursor_login"
DEFAULT_MODEL = "auto"  # required — without this Cursor demands plan upgrade


AGENT_ID = "cursor"


async def run(prompt: str, model: str | None, timeout: int, workspace: str | None = None, keep: bool = False, consolidate: bool = False):
    if not shutil.which(CMD):
        print(f"{C.RED}'{CMD}' not found in PATH{C.RESET}")
        sys.exit(1)

    tmpdir, should_cleanup = setup_workspace(AGENT_ID, workspace, keep)
    client = ProbeClient(consolidate=consolidate)

    print(f"{C.BOLD}=== Probe: Cursor Agent ==={C.RESET}")
    print(f"  Binary:    {shutil.which(CMD)}")
    print(f"  Workspace: {tmpdir}")
    print(f"  Timeout:   {timeout}s")
    print()

    try:
        async with spawn_agent_process(client, CMD, *ARGS, cwd=tmpdir) as (conn, proc):
            log("spawn", C.GREEN, f"PID {proc.pid}")

            init = await phase_initialize(conn)

            info = getattr(init, "agent_info", None)
            if info:
                log("agent", C.CYAN, f"{info.name} v{getattr(info, 'version', '?')}")
            caps = getattr(init, "agent_capabilities", None)
            if caps:
                pc = getattr(caps, "prompt_capabilities", None)
                log("caps", C.DIM, f"loadSession={caps.load_session} image={pc and pc.image} audio={pc and pc.audio} embeddedContext={pc and pc.embedded_context}")

            # Auth — may or may not exist
            auth_methods = getattr(init, "auth_methods", []) or []
            if auth_methods:
                await phase_authenticate(conn, init, prefer_method=AUTH_PREFER)
            else:
                log("auth", C.DIM, "no auth methods")

            session = await phase_session(conn, tmpdir)

            # Model — try if provided, don't assume it works
            target = model or DEFAULT_MODEL
            if target:
                await phase_set_model(conn, session.session_id, target)

            await phase_prompt(conn, session.session_id, prompt, timeout=timeout - 20)

            show_workspace(tmpdir)
            show_stats(client)
            show_consolidated(client)

            # Key question: did the agent call our fs/terminal methods?
            print(f"\n{C.BOLD}--- Execution Model ---{C.RESET}")
            if client.stats.fs_writes > 0 or client.stats.terminal_creates > 0:
                print(f"  {C.CYAN}DELEGATED — agent used client fs/terminal handlers{C.RESET}")
            else:
                print(f"  {C.YELLOW}LOCAL — agent executed without calling client handlers{C.RESET}")
                print(f"  {C.DIM}Check workspace to see if files were created directly on disk{C.RESET}")
    finally:
        cleanup_workspace(tmpdir, should_cleanup)


def main():
    parser = argparse.ArgumentParser(description="Cursor Agent ACP probe")
    add_common_args(parser)
    args = parser.parse_args()

    asyncio.run(run_with_timeout(
        run(args.prompt, args.model, args.timeout, workspace=args.workspace, keep=args.keep, consolidate=args.consolidate),
        timeout=args.timeout,
        agent_id="cursor_agent",
    ))


if __name__ == "__main__":
    main()
