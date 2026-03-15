#!/usr/bin/env python3
"""OpenCode ACP probe.

Known:
- Version 1.2.26, installed
- Has `opencode acp` subcommand
- Default --port 0 (HTTP), but without --port may use stdio
- Auth: Google OAuth configured via `opencode providers login`
- Execution model: UNKNOWN

Discovery goals:
- Does `opencode acp` without --port use stdio? Or always HTTP?
- What authMethods does it return?
- What execution model? Delegated or local?
- What models are available?
- Does the intro.sh exercise complete?
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


# OpenCode acp — try stdio first (no --port flag)
# If this doesn't work, we need HTTP transport with port discovery
CMD = "opencode"
ARGS = ["acp"]  # no --port = stdio transport (hypothesis)
DEFAULT_MODEL = None  # discover from session


AGENT_ID = "opencode"


async def run(prompt: str, model: str | None, timeout: int, workspace: str | None = None, keep: bool = False, consolidate: bool = False):
    if not shutil.which(CMD):
        print(f"{C.RED}'{CMD}' not found in PATH{C.RESET}")
        sys.exit(1)

    tmpdir, should_cleanup = setup_workspace(AGENT_ID, workspace, keep)
    client = ProbeClient(consolidate=consolidate)

    print(f"{C.BOLD}=== Probe: OpenCode ==={C.RESET}")
    print(f"  Binary:    {shutil.which(CMD)}")
    print(f"  Args:      {ARGS}")
    print(f"  Workspace: {tmpdir}")
    print(f"  Timeout:   {timeout}s")
    print(f"  Transport: stdio (hypothesis — no --port flag)")
    print()

    try:
        async with spawn_agent_process(client, CMD, *ARGS, cwd=tmpdir) as (conn, proc):
            log("spawn", C.GREEN, f"PID {proc.pid}")

            # Phase 1: Initialize — will this work over stdio?
            try:
                init = await phase_initialize(conn, timeout=20)
            except asyncio.TimeoutError:
                log("init", C.RED, "TIMEOUT — stdio transport may not work. Try HTTP with --port 0")
                return
            except Exception as e:
                log("init", C.RED, f"FAILED: {e}")
                return

            info = getattr(init, "agent_info", None)
            if info:
                log("agent", C.CYAN, f"{getattr(info, 'name', '?')} v{getattr(info, 'version', '?')}")
            caps = getattr(init, "agent_capabilities", None)
            if caps:
                pc = getattr(caps, "prompt_capabilities", None)
                log("caps", C.DIM, f"loadSession={caps.load_session} image={pc and pc.image} audio={pc and pc.audio} embeddedContext={pc and pc.embedded_context}")

            # Phase 2: Auth
            auth_methods = getattr(init, "auth_methods", []) or []
            if auth_methods:
                log("auth", C.DIM, f"methods: {[am.id for am in auth_methods]}")
                try:
                    await phase_authenticate(conn, init)
                except Exception as e:
                    log("auth", C.YELLOW, f"auth failed: {e} — trying to continue without")
            else:
                log("auth", C.DIM, "no auth methods — agent handles auth internally")

            # Phase 3: Session
            try:
                session = await phase_session(conn, tmpdir)
            except Exception as e:
                log("session", C.RED, f"FAILED: {e}")
                return

            # Phase 3.5: Model switch if requested
            target = model or DEFAULT_MODEL
            if target:
                await phase_set_model(conn, session.session_id, target)

            # Phase 4: Prompt
            await phase_prompt(conn, session.session_id, prompt, timeout=timeout - 30)

            show_workspace(tmpdir)
            show_stats(client)
            show_consolidated(client)

            # Execution model detection
            print(f"\n{C.BOLD}--- Execution Model ---{C.RESET}")
            if client.stats.fs_writes > 0 or client.stats.terminal_creates > 0:
                print(f"  {C.CYAN}DELEGATED — agent used client fs/terminal handlers{C.RESET}")
            else:
                print(f"  {C.YELLOW}LOCAL or UNKNOWN — no client fs/terminal calls observed{C.RESET}")
    finally:
        cleanup_workspace(tmpdir, should_cleanup)


def main():
    parser = argparse.ArgumentParser(description="OpenCode ACP probe")
    add_common_args(parser)
    args = parser.parse_args()

    asyncio.run(run_with_timeout(
        run(args.prompt, args.model, args.timeout, workspace=args.workspace, keep=args.keep, consolidate=args.consolidate),
        timeout=args.timeout,
        agent_id="opencode",
    ))


if __name__ == "__main__":
    main()
