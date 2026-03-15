#!/usr/bin/env python3
"""Gemini CLI ACP probe.

Known behaviors (from integration effort):
- Delegated execution: Gemini delegates all fs/terminal to client
- Auth: oauth-personal (uses cached Google creds from `gemini auth login`)
- Models: dynamic from session/new (7 models), default auto-gemini-3
- ACP flag: --acp (not --experimental-acp)
- Permission format: AllowedOutcome required
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


CMD = "gemini"
ARGS = ["--acp"]
AUTH_PREFER = "oauth-personal"
DEFAULT_MODEL = "gemini-3-flash-preview"


AGENT_ID = "gemini"


async def run(prompt: str, model: str | None, timeout: int, workspace: str | None = None, keep: bool = False, consolidate: bool = False):
    if not shutil.which(CMD):
        print(f"{C.RED}'{CMD}' not found in PATH{C.RESET}")
        sys.exit(1)

    tmpdir, should_cleanup = setup_workspace(AGENT_ID, workspace, keep)
    client = ProbeClient(consolidate=consolidate)

    print(f"{C.BOLD}=== Probe: Gemini CLI ==={C.RESET}")
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
                log("agent", C.CYAN, f"{info.name} v{info.version}")
            caps = getattr(init, "agent_capabilities", None)
            if caps:
                pc = getattr(caps, "prompt_capabilities", None)
                log("caps", C.DIM, f"loadSession={caps.load_session} image={pc and pc.image} audio={pc and pc.audio}")

            await phase_authenticate(conn, init, prefer_method=AUTH_PREFER)

            session = await phase_session(conn, tmpdir)

            target = model or DEFAULT_MODEL
            if target:
                await phase_set_model(conn, session.session_id, target)

            await phase_prompt(conn, session.session_id, prompt, timeout=timeout - 20)

            show_workspace(tmpdir)
            show_stats(client)
            show_consolidated(client)
    finally:
        cleanup_workspace(tmpdir, should_cleanup)


def main():
    parser = argparse.ArgumentParser(description="Gemini CLI ACP probe")
    add_common_args(parser)
    args = parser.parse_args()

    asyncio.run(run_with_timeout(
        run(args.prompt, args.model, args.timeout, workspace=args.workspace, keep=args.keep, consolidate=args.consolidate),
        timeout=args.timeout,
        agent_id="gemini_cli",
    ))


if __name__ == "__main__":
    main()
