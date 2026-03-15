"""Shared ACP probe harness.

Provides ProbeClient (fs/terminal executor, permission gate, update logger)
and utilities for per-agent probe scripts.

Each agent probe imports this and defines its own flow.
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass, field

import acp
from acp import spawn_agent_process, text_block
from acp.schema import AllowedOutcome, ClientCapabilities, FileSystemCapability

# Suppress SDK background noise
logging.getLogger("root").setLevel(logging.CRITICAL)
logging.getLogger("acp").setLevel(logging.WARNING)

# Suppress "Event loop is closed" noise from subprocess transport GC on Python 3.10
from asyncio import base_subprocess
_orig_del = base_subprocess.BaseSubprocessTransport.__del__
def _quiet_del(self):
    try:
        _orig_del(self)
    except RuntimeError:
        pass
base_subprocess.BaseSubprocessTransport.__del__ = _quiet_del

DEFAULT_PROMPT = (
    "Create a bash script called intro.sh that prints your coding engine name "
    "and today's date (use the `date` command). Make it executable with chmod +x, "
    "then run it and show the output."
)


# ---------------------------------------------------------------------------
# Colors & logging
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
# Call tracker — records what the agent actually called on us
# ---------------------------------------------------------------------------

@dataclass
class CallStats:
    fs_reads: int = 0
    fs_writes: int = 0
    terminal_creates: int = 0
    terminal_outputs: int = 0
    terminal_exits: int = 0
    permissions_requested: int = 0
    permissions_approved: int = 0
    session_updates: int = 0
    unknown_updates: list = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.fs_reads or self.fs_writes:
            lines.append(f"fs: {self.fs_reads} reads, {self.fs_writes} writes")
        if self.terminal_creates:
            lines.append(f"terminal: {self.terminal_creates} created, {self.terminal_outputs} output calls, {self.terminal_exits} exits")
        if self.permissions_requested:
            lines.append(f"permissions: {self.permissions_requested} requested, {self.permissions_approved} approved")
        lines.append(f"session_updates: {self.session_updates}")
        if self.unknown_updates:
            lines.append(f"unknown update types: {self.unknown_updates}")
        if not self.fs_reads and not self.fs_writes and not self.terminal_creates:
            lines.append("NO client fs/terminal calls — agent likely executes locally")
        return " | ".join(lines)


# ---------------------------------------------------------------------------
# ProbeClient
# ---------------------------------------------------------------------------

class ProbeClient(acp.Client):
    """Full ACP Client for probing. Executes fs/terminal locally, auto-approves."""

    def __init__(self):
        self._terminals: dict = {}
        self._tid = 0
        self.stats = CallStats()

    # --- Filesystem ---

    async def read_text_file(self, path, session_id, limit=None, line=None, **kw):
        self.stats.fs_reads += 1
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
        self.stats.fs_writes += 1
        log("fs:write", C.GREEN, f"{path} ({len(content)} bytes)")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return acp.WriteTextFileResponse()

    # --- Terminal ---

    async def create_terminal(self, command, session_id, args=None, cwd=None, env=None, output_byte_limit=None, **kw):
        self.stats.terminal_creates += 1
        self._tid += 1
        tid = f"t{self._tid}"
        full_cmd = [command] + (args or [])
        log("term:run", C.GREEN, f"[{tid}] {' '.join(full_cmd)}")

        env_dict = dict(os.environ)
        if env:
            for e in env:
                env_dict[getattr(e, 'name', '')] = getattr(e, 'value', '')

        # If command contains shell operators, run through bash -c
        shell_cmd = " ".join(full_cmd)
        if any(op in shell_cmd for op in ("&&", "||", "|", ";", ">", "<")):
            exec_cmd = ["bash", "-c", shell_cmd]
        else:
            exec_cmd = full_cmd

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd or os.getcwd(),
                env=env_dict,
            )
            self._terminals[tid] = proc
        except Exception as e:
            log("term:err", C.RED, f"[{tid}] Failed: {e}")
            self._terminals[tid] = None
        return acp.CreateTerminalResponse(terminalId=tid)

    async def terminal_output(self, session_id, terminal_id, **kw):
        self.stats.terminal_outputs += 1
        proc = self._terminals.get(terminal_id)
        if not proc or not proc.stdout:
            return acp.TerminalOutputResponse(output="", truncated=False)
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
        self.stats.terminal_exits += 1
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

    # --- Permissions ---

    async def request_permission(self, options, session_id, tool_call, **kw):
        self.stats.permissions_requested += 1
        title = getattr(tool_call, "title", "unknown") if tool_call else "unknown"
        kind = getattr(tool_call, "kind", "") if tool_call else ""
        log("GATE", C.MAGENTA, f"{title} (kind={kind})")

        if tool_call and getattr(tool_call, "content", None):
            for block in tool_call.content:
                actual = getattr(block, "actual_instance", block)
                if hasattr(actual, "new_text") and hasattr(actual, "path"):
                    log("GATE", C.DIM, f"  {actual.path}")
                    for line in (actual.new_text or "").split("\n")[:8]:
                        print(f"           {C.DIM}| {line}{C.RESET}", flush=True)

        for opt in (options or []):
            if opt.kind and "allow_once" in str(opt.kind):
                self.stats.permissions_approved += 1
                log("GATE", C.GREEN, f"→ approved ({opt.option_id})")
                return acp.RequestPermissionResponse(
                    outcome=AllowedOutcome(option_id=opt.option_id, outcome="selected")
                )

        oid = options[0].option_id if options else "proceed_once"
        self.stats.permissions_approved += 1
        log("GATE", C.GREEN, f"→ approved ({oid})")
        return acp.RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=oid, outcome="selected")
        )

    # --- Session updates ---

    async def session_update(self, session_id, update, **kw):
        self.stats.session_updates += 1
        if not update:
            return

        ut = getattr(update, "session_update", "") or ""

        if ut == "agent_message_chunk":
            content = getattr(update, "content", None)
            if content:
                actual = getattr(content, "actual_instance", content)
                text = getattr(actual, "text", None)
                if text:
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

        if ut in ("available_commands_update", "config_option_update",
                   "current_mode_update", "session_info_update", "usage_update"):
            return

        # Unknown — log it for the effort log
        self.stats.unknown_updates.append(ut)
        log(ut or "unknown_update", C.YELLOW, "(new update type — document this)")

    # --- Extensions ---

    async def ext_method(self, method, params):
        log("ext", C.YELLOW, f"method={method}")
        return {}

    async def ext_notification(self, method, params):
        pass

    def on_connect(self, conn):
        pass


# ---------------------------------------------------------------------------
# Phase runners — each phase has its own timeout and error handling
# ---------------------------------------------------------------------------

async def phase_initialize(conn, timeout=15):
    """Run initialize. Returns init result or raises."""
    log("phase", C.CYAN, "initialize")
    return await asyncio.wait_for(
        conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapability(read_text_file=True, write_text_file=True),
                terminal=True,
            ),
            client_info={"name": "nautex-probe", "title": "Nautex Probe", "version": "0.3.0"},
        ),
        timeout=timeout,
    )


async def phase_authenticate(conn, init_result, prefer_method=None, timeout=15):
    """Run authenticate if authMethods available. Returns True if authed."""
    auth_methods = getattr(init_result, "auth_methods", []) or []
    if not auth_methods:
        log("auth", C.DIM, "no auth methods — skipping")
        return False

    method = auth_methods[0]
    if prefer_method:
        for am in auth_methods:
            if am.id == prefer_method:
                method = am
                break
    else:
        for am in auth_methods:
            if "oauth" in (am.id or "") or "login" in (am.id or ""):
                method = am
                break

    log("auth", C.CYAN, f"{method.id} ({method.name})")
    await asyncio.wait_for(conn.authenticate(method_id=method.id), timeout=timeout)
    log("auth", C.GREEN, "OK")
    return True


async def phase_session(conn, cwd, timeout=15):
    """Create session. Returns session result."""
    log("phase", C.CYAN, "session/new")
    session = await asyncio.wait_for(
        conn.new_session(cwd=cwd, mcp_servers=[]),
        timeout=timeout,
    )
    log("session", C.GREEN, session.session_id)

    models_info = getattr(session, "models", None)
    if models_info and hasattr(models_info, "available_models") and models_info.available_models:
        ids = [m.model_id for m in models_info.available_models]
        log("models", C.DIM, f"{ids}")
        log("models", C.DIM, f"current={models_info.current_model_id}")

    return session


async def phase_set_model(conn, session_id, model_id, timeout=10):
    """Switch model. Returns True on success."""
    try:
        await asyncio.wait_for(
            conn.set_session_model(session_id=session_id, model_id=model_id),
            timeout=timeout,
        )
        log("model", C.GREEN, f"→ {model_id}")
        return True
    except Exception as e:
        log("model", C.YELLOW, f"switch failed: {e}")
        return False


async def phase_prompt(conn, session_id, prompt, timeout=90):
    """Send prompt and wait for completion. Returns prompt result."""
    log("prompt", C.CYAN, prompt[:100])
    print(f"\n{C.BOLD}--- Agent Output ---{C.RESET}\n", flush=True)

    result = await asyncio.wait_for(
        conn.prompt(session_id=session_id, prompt=[text_block(prompt)]),
        timeout=timeout,
    )

    stop = getattr(result, "stop_reason", "unknown")
    print(f"\n\n{C.GREEN}{C.BOLD}--- Done (stopReason: {stop}) ---{C.RESET}\n", flush=True)
    return result


def show_workspace(tmpdir: str):
    """Print workspace contents and intro.sh if present."""
    print(f"{C.BOLD}--- Workspace ---{C.RESET}")
    found = False
    for item in sorted(Path(tmpdir).rglob("*")):
        if item.is_file() and not item.name.startswith("."):
            print(f"  {item.relative_to(tmpdir)} ({item.stat().st_size} bytes)")
            found = True
    if not found:
        print(f"  {C.DIM}(empty){C.RESET}")

    intro = Path(tmpdir) / "intro.sh"
    if intro.exists():
        print(f"\n{C.BOLD}--- intro.sh ---{C.RESET}")
        print(intro.read_text())


def show_stats(client: ProbeClient):
    """Print call statistics summary."""
    print(f"\n{C.BOLD}--- Client Call Stats ---{C.RESET}")
    print(f"  {client.stats.summary()}")


# ---------------------------------------------------------------------------
# Runner wrapper
# ---------------------------------------------------------------------------

def setup_workspace(agent_id: str, workspace: str | None = None, keep: bool = False) -> tuple[str, bool]:
    """Create or use a workspace directory. Returns (path, should_cleanup)."""
    if workspace:
        Path(workspace).mkdir(parents=True, exist_ok=True)
        return workspace, False  # user-provided, never cleanup
    tmpdir = tempfile.mkdtemp(prefix=f"nautex-probe-{agent_id}-")
    return tmpdir, not keep


def cleanup_workspace(tmpdir: str, should_cleanup: bool):
    """Remove workspace if it was auto-created and --keep not set."""
    if should_cleanup:
        shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        print(f"\n{C.DIM}Workspace kept: {tmpdir}{C.RESET}")


def add_common_args(parser):
    """Add shared CLI args to a probe's argument parser."""
    parser.add_argument("-p", "--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("-m", "--model", default=None)
    parser.add_argument("-t", "--timeout", type=int, default=90)
    parser.add_argument("-w", "--workspace", default=None, help="Workspace directory (default: auto temp dir)")
    parser.add_argument("--keep", action="store_true", help="Keep workspace after probe finishes")


async def run_with_timeout(coro, timeout: int, agent_id: str):
    """Run a probe coroutine with global timeout and clean exit."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
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
