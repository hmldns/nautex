#!/usr/bin/env python3
"""Hermes ACP scenario runner with full raw-signal capture.

Spawns hermes-acp once per scenario, captures every signal at its raw
pydantic shape (full model_dump including `_meta`), and writes a per-scenario
artifact directory. A second pass aggregates findings into a markdown report.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/probes/report_hermes.py all
    PYTHONPATH=src .venv/bin/python scripts/probes/report_hermes.py fs_read
"""

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import acp
from acp import spawn_agent_process, text_block
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    FileSystemCapabilities,
    McpServerStdio,
)


CMD = "hermes-acp"


def _dump(obj):
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=False)
    if isinstance(obj, (list, tuple)):
        return [_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


class CapturingClient(acp.Client):
    """Full ACP client that captures every inbound signal verbatim to JSONL."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.updates_log = (out_dir / "updates.jsonl").open("w")
        self.perms_log = (out_dir / "perms.jsonl").open("w")
        self.fs_log = (out_dir / "fs_calls.jsonl").open("w")
        self.term_log = (out_dir / "terminal_calls.jsonl").open("w")
        self.ext_log = (out_dir / "ext.jsonl").open("w")
        self._terminals = {}
        self._tid = 0
        self.permissions_requested = 0
        self.permissions_approved = 0
        self.fs_reads = 0
        self.fs_writes = 0
        self.terminal_creates = 0

    # ---- filesystem callbacks (agent → us) ----
    async def read_text_file(self, path, session_id, limit=None, line=None, **kw):
        self.fs_reads += 1
        rec = {"ts": time.time(), "op": "read", "path": path, "session_id": session_id,
               "limit": limit, "line": line, "extra": _dump(kw)}
        self.fs_log.write(json.dumps(rec, default=str) + "\n")
        self.fs_log.flush()
        try:
            text = Path(path).read_text()
        except FileNotFoundError:
            text = ""
        return acp.ReadTextFileResponse(content=text)

    async def write_text_file(self, content, path, session_id, **kw):
        self.fs_writes += 1
        rec = {"ts": time.time(), "op": "write", "path": path, "size": len(content),
               "session_id": session_id, "extra": _dump(kw)}
        self.fs_log.write(json.dumps(rec, default=str) + "\n")
        self.fs_log.flush()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return acp.WriteTextFileResponse()

    # ---- terminal callbacks ----
    async def create_terminal(self, command, session_id, args=None, cwd=None, env=None, output_byte_limit=None, **kw):
        self._tid += 1
        tid = f"t{self._tid}"
        self.terminal_creates += 1
        rec = {"ts": time.time(), "op": "create", "tid": tid, "command": command,
               "args": list(args or []), "cwd": cwd, "env": _dump(env), "session_id": session_id}
        self.term_log.write(json.dumps(rec, default=str) + "\n")
        self.term_log.flush()
        try:
            proc = await asyncio.create_subprocess_exec(
                command, *(args or []),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            self._terminals[tid] = proc
        except Exception as e:
            self.term_log.write(json.dumps({"ts": time.time(), "op": "create_err", "tid": tid, "err": repr(e)}) + "\n")
            self.term_log.flush()
            self._terminals[tid] = None
        return acp.CreateTerminalResponse(terminalId=tid)

    async def terminal_output(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc or not proc.stdout:
            return acp.TerminalOutputResponse(output="", truncated=False)
        try:
            data = await asyncio.wait_for(proc.stdout.read(65536), timeout=5.0)
        except asyncio.TimeoutError:
            return acp.TerminalOutputResponse(output="", truncated=False)
        return acp.TerminalOutputResponse(output=data.decode("utf-8", errors="replace"), truncated=False)

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc:
            return acp.WaitForTerminalExitResponse(exitCode=1)
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            code = -1
        return acp.WaitForTerminalExitResponse(exitCode=code or 0)

    async def kill_terminal(self, session_id, terminal_id, **kw):
        proc = self._terminals.pop(terminal_id, None)
        if proc and proc.returncode is None:
            proc.kill()
        return acp.KillTerminalCommandResponse()

    async def release_terminal(self, session_id, terminal_id, **kw):
        self._terminals.pop(terminal_id, None)
        return acp.ReleaseTerminalResponse()

    # ---- permission gating ----
    async def request_permission(self, options, session_id, tool_call, **kw):
        self.permissions_requested += 1
        rec = {
            "ts": time.time(),
            "session_id": session_id,
            "options": _dump(options),
            "tool_call": _dump(tool_call),
            "extra": _dump(kw),
        }
        self.perms_log.write(json.dumps(rec, default=str) + "\n")
        self.perms_log.flush()

        oid = options[0].option_id if options else "proceed_once"
        for opt in (options or []):
            kind_str = str(getattr(opt, "kind", ""))
            if "allow_once" in kind_str or "allow_session" in kind_str:
                oid = opt.option_id
                break
        self.permissions_approved += 1
        return acp.RequestPermissionResponse(outcome=AllowedOutcome(option_id=oid, outcome="selected"))

    # ---- session updates (the goldmine) ----
    async def session_update(self, session_id, update, **kw):
        rec = {
            "ts": time.time(),
            "session_id": session_id,
            "update": _dump(update),
        }
        self.updates_log.write(json.dumps(rec, default=str) + "\n")
        self.updates_log.flush()

    # ---- extension method/notification ----
    async def ext_method(self, method, params):
        rec = {"ts": time.time(), "type": "ext_method", "method": method, "params": _dump(params)}
        self.ext_log.write(json.dumps(rec, default=str) + "\n")
        self.ext_log.flush()
        return {}

    async def ext_notification(self, method, params):
        rec = {"ts": time.time(), "type": "ext_notification", "method": method, "params": _dump(params)}
        self.ext_log.write(json.dumps(rec, default=str) + "\n")
        self.ext_log.flush()

    def on_connect(self, conn):
        pass

    def close(self):
        for f in (self.updates_log, self.perms_log, self.fs_log, self.term_log, self.ext_log):
            try:
                f.close()
            except Exception:
                pass


SCENARIOS = {
    "fs_read": {
        "prompt": "Read the file notes.md in the current directory and tell me exactly what it contains. Quote it verbatim.",
        "seed_files": {"notes.md": "Hermes ACP probe notes.\n- token A: alpha\n- token B: beta\n- secret: PROBE_MARKER_42\n"},
        "mcp_servers": [],
    },
    "fs_write": {
        "prompt": "Create a file named hello.txt in the current directory containing the single word 'hi'. Do not add any other content.",
        "seed_files": {},
        "mcp_servers": [],
    },
    "web_search": {
        "prompt": "Search the web for 'Agent Client Protocol Zed' and report the URL of the top result.",
        "seed_files": {},
        "mcp_servers": [],
    },
    "subagent": {
        "prompt": "Use any subagent, sub-task, or skill mechanism you have to count the .txt files in the current directory and report the count. If no subagent mechanism is available, say so explicitly.",
        "seed_files": {"a.txt": "a", "b.txt": "b", "c.txt": "c"},
        "mcp_servers": [],
    },
    "mcp_injected": {
        "prompt": "Use the injected MCP server named 'fetch' to retrieve https://example.com and report the value of the <title> tag.",
        "seed_files": {},
        "mcp_servers": "fetch",
    },
}


def _build_mcp(spec):
    if spec == "fetch":
        return [McpServerStdio(name="fetch", command="uvx", args=["mcp-server-fetch"], env=[])]
    return list(spec) if spec else []


async def run_scenario(scenario_id: str, out_root: Path, timeout: int) -> dict:
    scn = SCENARIOS[scenario_id]
    out_dir = out_root / scenario_id
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / "workdir"
    workdir.mkdir(exist_ok=True)
    for fname, content in scn["seed_files"].items():
        (workdir / fname).write_text(content)

    client = CapturingClient(out_dir)
    mcp_servers = _build_mcp(scn["mcp_servers"]) if isinstance(scn["mcp_servers"], str) else scn["mcp_servers"]

    summary = {
        "scenario": scenario_id,
        "prompt": scn["prompt"],
        "seed_files": list(scn["seed_files"].keys()),
        "mcp_servers": [getattr(s, "name", "?") for s in mcp_servers],
        "workdir": str(workdir),
        "status": "pending",
    }

    try:
        async with spawn_agent_process(client, CMD, cwd=str(workdir)) as (conn, proc):
            summary["pid"] = proc.pid

            init = await asyncio.wait_for(
                conn.initialize(
                    protocol_version=acp.PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(
                        fs=FileSystemCapabilities(read_text_file=True, write_text_file=True),
                        terminal=True,
                    ),
                    client_info={"name": "nautex-hermes-report", "title": "Hermes Report", "version": "0.1.0"},
                ),
                timeout=20,
            )
            (out_dir / "init.json").write_text(json.dumps(_dump(init), indent=2, default=str))

            session = await asyncio.wait_for(
                conn.new_session(cwd=str(workdir), mcp_servers=mcp_servers),
                timeout=90,
            )
            (out_dir / "session.json").write_text(json.dumps(_dump(session), indent=2, default=str))
            summary["session_id"] = getattr(session, "session_id", None)

            result = await asyncio.wait_for(
                conn.prompt(session_id=session.session_id, prompt=[text_block(scn["prompt"])]),
                timeout=timeout - 30,
            )
            (out_dir / "prompt_result.json").write_text(json.dumps(_dump(result), indent=2, default=str))
            summary["stop_reason"] = getattr(result, "stop_reason", None)
            summary["status"] = "ok"

    except asyncio.TimeoutError:
        summary["status"] = "timeout"
    except Exception as e:
        summary["status"] = "error"
        summary["error"] = repr(e)
    finally:
        client.close()
        files = sorted(workdir.rglob("*"))
        summary["files_after"] = [
            {"path": str(f.relative_to(workdir)), "size": f.stat().st_size}
            for f in files if f.is_file()
        ]
        summary["permissions_requested"] = client.permissions_requested
        summary["permissions_approved"] = client.permissions_approved
        summary["fs_reads"] = client.fs_reads
        summary["fs_writes"] = client.fs_writes
        summary["terminal_creates"] = client.terminal_creates

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=list(SCENARIOS.keys()) + ["all"])
    parser.add_argument("-t", "--timeout", type=int, default=180)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if not shutil.which(CMD):
        print(f"ERROR: '{CMD}' not found in PATH", file=sys.stderr)
        sys.exit(1)

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(args.out) if args.out else Path(f"/tmp/hermes-acp-report/{ts}")
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"Artifact root: {out_root}", flush=True)

    targets = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    summaries = []
    for sid in targets:
        print(f"\n=== {sid} ===", flush=True)
        s = asyncio.run(run_scenario(sid, out_root, timeout=args.timeout))
        print(f"  status={s['status']} fs_reads={s['fs_reads']} fs_writes={s['fs_writes']} "
              f"perms={s['permissions_requested']} files_after={len(s['files_after'])}", flush=True)
        summaries.append(s)

    (out_root / "index.json").write_text(json.dumps(summaries, indent=2, default=str))
    print(f"\nDone. Artifacts: {out_root}", flush=True)


if __name__ == "__main__":
    main()
