#!/usr/bin/env python3
"""Nautex ACP Agent Probe — QA gate for the adapter normalization boundary.

Uses the official agent-client-protocol Python SDK to drive real agent binaries
end-to-end: spawn → initialize → authenticate → create session → send prompt →
stream updates → show results.

The default exercise: create intro.sh that prints the engine name + date, run it.

Usage:
    python scripts/probe_acp_agents.py <agent_id> [-t 90] [-m model] [-p "prompt"]
    python scripts/probe_acp_agents.py --list
"""

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import acp
from acp import text_block, spawn_agent_process
from acp.schema import ClientCapabilities

# Suppress SDK background task noise — these are non-fatal schema mismatches
logging.getLogger("root").setLevel(logging.CRITICAL)
logging.getLogger("acp").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Agent registry — absorbs all probing experience
# ---------------------------------------------------------------------------

AGENTS = {
    "gemini_cli": {
        "cmd": "gemini",
        "args": ["--acp"],
        "default_model": "gemini-3-flash-preview",
        "auth_prefer": "oauth-personal",
        "notes": "Pre-auth via 'gemini auth login'. --acp replaces deprecated --experimental-acp.",
    },
    "opencode": {
        "cmd": "opencode",
        "args": ["acp", "--port", "0"],
        "default_model": None,
        "auth_prefer": None,
        "notes": "HTTP transport, port discovered from stdout. Uses process_manager port_discovery.",
    },
    "goose": {
        "cmd": "goose",
        "args": ["acp"],
        "default_model": None,
        "auth_prefer": None,
        "notes": "Stdio transport. Model override via GOOSE_MODEL env var.",
    },
    "kiro_cli": {
        "cmd": "kiro-cli",
        "args": ["acp"],
        "default_model": None,
        "auth_prefer": None,
        "notes": "Stdio transport. Directory scope via --directory flag.",
    },
    "claude_code": {
        "cmd": "claude-agent-acp",
        "args": [],
        "default_model": None,
        "auth_prefer": None,
        "notes": "Requires @zed-industries/claude-agent-acp NPM wrapper.",
    },
    "cursor_agent": {
        "cmd": "cursor-agent",
        "args": ["acp"],
        "default_model": None,
        "auth_prefer": "cursor_login",
        "notes": "Pre-auth via 'cursor-agent login'. embeddedContext=false confirmed.",
    },
    "codex": {
        "cmd": "codex-acp",
        "args": [],
        "default_model": None,
        "auth_prefer": None,
        "notes": "Requires Zed codex-acp wrapper.",
    },
    "droid": {
        "cmd": "droid",
        "args": ["exec", "--output-format", "acp"],
        "default_model": None,
        "auth_prefer": None,
        "notes": "Custom HTTP API. WebSocket endpoint format differs from standard port discovery.",
    },
}

DEFAULT_PROMPT = (
    "Create a bash script called intro.sh that prints your coding engine name "
    "and today's date (use the `date` command). Make it executable with chmod +x, "
    "then run it and show the output."
)


# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"


def ts():
    return time.strftime("%H:%M:%S")


def log(tag: str, color: str, msg: str):
    print(f"{C.DIM}[{ts()}]{C.RESET} {color}[{tag}]{C.RESET} {msg}", flush=True)


# ---------------------------------------------------------------------------
# ACP Client — executes fs/terminal ops locally, auto-approves permissions
# ---------------------------------------------------------------------------

class ProbeClient(acp.Client):
    """Full ACP Client implementation for headless agent probing.

    - Executes file reads/writes directly on the workspace filesystem
    - Runs terminal commands as real subprocesses
    - Auto-approves all permission gates (allow_once)
    - Logs all session updates for observability
    """

    def __init__(self):
        self._terminals: dict = {}
        self._tid = 0

    # --- Filesystem ---

    async def read_text_file(self, path, session_id, limit=None, line=None, **kw):
        log("fs:read", C.BLUE, path)
        try:
            text = Path(path).read_text()
            if line is not None and limit is not None:
                lines = text.split("\n")
                text = "\n".join(lines[max(0, line - 1):line - 1 + limit])
            return acp.ReadTextFileResponse(content=text)
        except FileNotFoundError:
            log("fs:read", C.YELLOW, f"NOT FOUND: {path}")
            return acp.ReadTextFileResponse(content="")

    async def write_text_file(self, content, path, session_id, **kw):
        log("fs:WRITE", C.GREEN, f"{path} ({len(content)} bytes)")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        # Verify write landed
        exists = p.exists()
        log("fs:WRITE", C.GREEN if exists else C.RED, f"verified={exists} size={p.stat().st_size if exists else 0}")
        return acp.WriteTextFileResponse()

    # --- Terminal ---

    async def create_terminal(self, command, session_id, args=None, cwd=None, env=None, output_byte_limit=None, **kw):
        self._tid += 1
        tid = f"t{self._tid}"
        full_cmd = [command] + (args or [])
        log("term:run", C.GREEN, f"[{tid}] {' '.join(full_cmd)}")

        env_dict = dict(os.environ)
        if env:
            for e in env:
                env_dict[getattr(e, 'name', '')] = getattr(e, 'value', '')

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd or os.getcwd(),
                env=env_dict,
            )
            self._terminals[tid] = proc
        except Exception as e:
            log("term:err", C.RED, f"[{tid}] Failed to spawn: {e}")
            # Return terminal ID anyway — agent will get error on output read
            self._terminals[tid] = None
        return acp.CreateTerminalResponse(terminalId=tid)

    async def terminal_output(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc or not proc.stdout:
            return acp.TerminalOutputResponse(output="", isComplete=True)
        try:
            data = await asyncio.wait_for(proc.stdout.read(8192), timeout=10.0)
            output = data.decode("utf-8", errors="replace")
            if output.strip():
                for line in output.strip().split("\n"):
                    log("term:out", C.GREEN, f"[{terminal_id}] {line}")
            return acp.TerminalOutputResponse(output=output, truncated=False)
        except asyncio.TimeoutError:
            return acp.TerminalOutputResponse(output="", truncated=False)

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc:
            return acp.WaitForTerminalExitResponse(exitCode=1)
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            code = -1
        log("term:exit", C.BLUE, f"[{terminal_id}] code={code}")
        return acp.WaitForTerminalExitResponse(exitCode=code or 0)

    async def kill_terminal(self, session_id, terminal_id, **kw):
        proc = self._terminals.pop(terminal_id, None)
        if proc and proc.returncode is None:
            proc.kill()
        return acp.KillTerminalCommandResponse()

    async def release_terminal(self, session_id, terminal_id, **kw):
        self._terminals.pop(terminal_id, None)
        return acp.ReleaseTerminalResponse()

    # --- Permission gating ---

    async def request_permission(self, options, session_id, tool_call, **kw):
        title = getattr(tool_call, "title", "unknown") if tool_call else "unknown"
        kind = getattr(tool_call, "kind", "") if tool_call else ""
        log("GATE", C.MAGENTA, f"{title} (kind={kind})")

        # Show diff for edit operations
        if tool_call and getattr(tool_call, "content", None):
            for block in tool_call.content:
                actual = getattr(block, "actual_instance", block)
                if hasattr(actual, "new_text") and hasattr(actual, "path"):
                    log("GATE", C.DIM, f"  {actual.path}")
                    for line in (actual.new_text or "").split("\n")[:8]:
                        print(f"           {C.DIM}| {line}{C.RESET}", flush=True)

        # Auto-approve with allow_once
        from acp.schema import AllowedOutcome
        for opt in (options or []):
            if opt.kind and "allow_once" in str(opt.kind):
                log("GATE", C.GREEN, f"→ approved ({opt.option_id})")
                return acp.RequestPermissionResponse(
                    outcome=AllowedOutcome(option_id=opt.option_id, outcome="selected")
                )

        # Fallback
        oid = options[0].option_id if options else "proceed_once"
        log("GATE", C.GREEN, f"→ approved ({oid})")
        return acp.RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=oid, outcome="selected")
        )

    # --- Session updates (the normalized output stream) ---

    async def session_update(self, session_id, update, **kw):
        if not update:
            return

        ut = getattr(update, "session_update", "") or ""

        if ut == "agent_message_chunk":
            content = getattr(update, "content", None)
            if content:
                actual = getattr(content, "actual_instance", content)
                text = getattr(actual, "text", None)
                if text:
                    # Print without newline for streaming effect
                    sys.stdout.write(f"{C.BOLD}{text}{C.RESET}")
                    sys.stdout.flush()
            return

        if ut == "tool_call":
            tc = getattr(update, "tool_call", None)
            if tc:
                log("tool", C.BLUE, f"{getattr(tc, 'title', '')} (status={getattr(tc, 'status', '')})")
            return

        if ut == "tool_call_update":
            tc = getattr(update, "tool_call", None)
            if tc:
                status = getattr(tc, "status", "")
                title = getattr(tc, "title", "")
                if status in ("completed", "error"):
                    log(f"tool:{status}", C.BLUE if status == "completed" else C.RED, title)
            return

        if ut == "agent_thought_chunk":
            content = getattr(update, "content", None)
            if content:
                actual = getattr(content, "actual_instance", content)
                text = getattr(actual, "text", None)
                if text:
                    log("thought", C.DIM, text.replace("\n", " ")[:120])
            return

        if ut in ("available_commands_update", "config_option_update", "current_mode_update", "session_info_update"):
            return  # skip noise

        if ut == "usage_update":
            return  # skip token counts

        log(ut or "update", C.YELLOW, "")

    # --- Extension methods (agent-specific extras) ---

    async def ext_method(self, method, params):
        log("ext", C.YELLOW, f"method={method}")
        return {}

    async def ext_notification(self, method, params):
        log("ext", C.DIM, f"notification={method}")

    def on_connect(self, conn):
        pass


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

async def run_probe(agent_def: dict, tmpdir: str, prompt: str, model: str | None) -> None:
    cmd = agent_def["cmd"]
    client = ProbeClient()

    async with spawn_agent_process(client, cmd, *agent_def["args"], cwd=tmpdir) as (conn, proc):
        log("spawn", C.GREEN, f"PID {proc.pid}")

        # Initialize
        print(f"\n{C.BOLD}--- Initialize ---{C.RESET}")
        from acp.schema import FileSystemCapability
        init = await conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapability(read_text_file=True, write_text_file=True),
                terminal=True,
            ),
            client_info={"name": "nautex-probe", "title": "Nautex Probe", "version": "0.2.0"},
        )
        info = getattr(init, "agent_info", None)
        if info:
            log("agent", C.CYAN, f"{info.name} v{info.version}")
        caps = getattr(init, "agent_capabilities", None)
        if caps:
            pc = getattr(caps, "prompt_capabilities", None)
            log("caps", C.DIM, f"loadSession={caps.load_session} image={pc and pc.image} audio={pc and pc.audio}")

        # Authenticate
        auth_methods = getattr(init, "auth_methods", []) or []
        if auth_methods:
            print(f"\n{C.BOLD}--- Authenticate ---{C.RESET}")
            preferred = agent_def.get("auth_prefer")
            method = auth_methods[0]
            if preferred:
                for am in auth_methods:
                    if am.id == preferred:
                        method = am
                        break
            else:
                for am in auth_methods:
                    if "oauth" in (am.id or "") or "login" in (am.id or ""):
                        method = am
                        break
            log("auth", C.CYAN, f"{method.id} ({method.name})")
            await conn.authenticate(method_id=method.id)
            log("auth", C.GREEN, "OK")

        # Session
        print(f"\n{C.BOLD}--- Session ---{C.RESET}")
        session = await conn.new_session(cwd=tmpdir, mcp_servers=[])
        log("session", C.CYAN, session.session_id)

        models_info = getattr(session, "models", None)
        if models_info and hasattr(models_info, "available_models") and models_info.available_models:
            ids = [m.model_id for m in models_info.available_models]
            log("models", C.DIM, f"available={ids}")
            log("models", C.DIM, f"current={models_info.current_model_id}")

        target = model or agent_def.get("default_model")
        if target:
            try:
                await conn.set_session_model(session_id=session.session_id, model_id=target)
                log("model", C.GREEN, f"switched → {target}")
            except Exception as e:
                log("model", C.YELLOW, f"switch failed: {e} (using default)")

        # Prompt
        print(f"\n{C.BOLD}--- Prompt ---{C.RESET}")
        log("prompt", C.CYAN, prompt[:100])
        print(f"\n{C.BOLD}--- Agent Output ---{C.RESET}\n")

        result = await conn.prompt(
            session_id=session.session_id,
            prompt=[text_block(prompt)],
        )

        stop = getattr(result, "stop_reason", "unknown")
        print(f"\n\n{C.GREEN}{C.BOLD}--- Done (stopReason: {stop}) ---{C.RESET}\n")

        # Workspace inspection
        print(f"{C.BOLD}--- Workspace ---{C.RESET}")
        files_found = False
        for item in sorted(Path(tmpdir).rglob("*")):
            if item.is_file() and not item.name.startswith("."):
                rel = item.relative_to(tmpdir)
                print(f"  {rel} ({item.stat().st_size} bytes)")
                files_found = True
        if not files_found:
            print(f"  {C.DIM}(empty){C.RESET}")

        intro = Path(tmpdir) / "intro.sh"
        if intro.exists():
            print(f"\n{C.BOLD}--- intro.sh ---{C.RESET}")
            print(intro.read_text())


async def probe(agent_id: str, prompt: str, model: str | None, timeout: int) -> None:
    agent = AGENTS.get(agent_id)
    if not agent:
        print(f"{C.RED}Unknown agent: {agent_id}{C.RESET}")
        print(f"Available: {', '.join(AGENTS.keys())}")
        sys.exit(1)

    cmd = agent["cmd"]
    if not shutil.which(cmd):
        print(f"{C.RED}'{cmd}' not found in PATH{C.RESET}")
        sys.exit(1)

    tmpdir = tempfile.mkdtemp(prefix=f"nautex-probe-{agent_id}-")

    print(f"{C.BOLD}=== Nautex ACP Probe ==={C.RESET}")
    print(f"  Agent:     {agent_id} ({shutil.which(cmd)})")
    print(f"  Workspace: {tmpdir}")
    print(f"  Timeout:   {timeout}s")
    if agent.get("notes"):
        print(f"  Notes:     {agent['notes']}")

    try:
        await asyncio.wait_for(run_probe(agent, tmpdir, prompt, model), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"\n{C.RED}TIMEOUT ({timeout}s). Exiting.{C.RESET}")
        sys.exit(1)
    except acp.exceptions.RequestError as e:
        print(f"\n{C.RED}ACP Error: {e}{C.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{C.RED}Error: {e}{C.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Nautex ACP Agent Probe")
    parser.add_argument("agent_id", nargs="?", help="Agent to probe")
    parser.add_argument("-p", "--prompt", default=DEFAULT_PROMPT, help="Prompt text")
    parser.add_argument("-m", "--model", default=None, help="Model override")
    parser.add_argument("-t", "--timeout", type=int, default=90, help="Timeout seconds (default: 90)")
    parser.add_argument("-l", "--list", action="store_true", help="List agents")
    args = parser.parse_args()

    if args.list or not args.agent_id:
        print(f"{C.BOLD}Available agents:{C.RESET}")
        for aid, info in AGENTS.items():
            ok = shutil.which(info["cmd"])
            status = f"{C.GREEN}OK{C.RESET}" if ok else f"{C.RED}MISSING{C.RESET}"
            dm = info.get("default_model") or "-"
            print(f"  {aid:18s} [{status}] cmd={info['cmd']:20s} model={dm}")
        return

    asyncio.run(probe(args.agent_id, args.prompt, args.model, args.timeout))


if __name__ == "__main__":
    main()
