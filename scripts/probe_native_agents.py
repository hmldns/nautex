#!/usr/bin/env python3
"""Diagnostic probe for native ACP agent binaries.

Spawns each known agent binary locally, sends a JSON-RPC `initialize`
payload over stdin, and checks whether stdout responds with valid ACP format.
Provides a debug log of the transport behavior.

Usage:
    python scripts/probe_native_agents.py [agent_id ...]

    With no arguments, probes all known agents.
    With arguments, probes only the named agents (e.g., gemini_cli opencode).

Reference: PRD-128
"""

import asyncio
import json
import os
import shutil
import signal
import sys
import time

# Agent binary definitions: (agent_id, executable, args, needs_port_discovery)
AGENTS = [
    ("gemini_cli",    "gemini",       ["--experimental-acp"],              False),
    ("opencode",      "opencode",     ["acp", "--port", "0"],              True),
    ("goose",         "goose",        ["acp"],                             False),
    ("kiro_cli",      "kiro-cli",     ["acp"],                             False),
    ("claude_code",   "claude-agent-acp", [],                              False),
    ("cursor_agent",  "cursor-agent", ["acp"],                             False),
    ("codex",         "codex-acp",    [],                                  False),
    ("droid",         "droid",        ["daemon", "--port", "0"],            True),
]

INITIALIZE_REQUEST = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "nautex-probe",
            "version": "0.1.0",
        },
    },
}) + "\n"

PROBE_TIMEOUT = 10.0  # seconds


def log(agent_id: str, level: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{agent_id}] {level}: {msg}")


async def probe_agent(agent_id: str, executable: str, args: list, needs_port: bool) -> dict:
    """Probe a single agent binary and return results."""
    result = {"agent_id": agent_id, "executable": executable, "installed": False, "acp_response": None, "error": None}

    # Check if binary exists
    if not shutil.which(executable):
        result["error"] = f"Binary '{executable}' not found in PATH"
        log(agent_id, "SKIP", result["error"])
        return result

    result["installed"] = True
    log(agent_id, "INFO", f"Found binary: {shutil.which(executable)}")
    log(agent_id, "INFO", f"Launching: {executable} {' '.join(args)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            executable, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        # For port-based agents, read until we find the port line
        if needs_port:
            log(agent_id, "INFO", "Waiting for port binding on stdout...")
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=PROBE_TIMEOUT)
                    if not line:
                        break
                    decoded = line.decode("utf-8").strip()
                    log(agent_id, "STDOUT", decoded)
                    if "port" in decoded.lower():
                        log(agent_id, "INFO", f"Port binding detected: {decoded}")
                        break
            except asyncio.TimeoutError:
                result["error"] = "Timeout waiting for port binding"
                log(agent_id, "ERROR", result["error"])

        # Send initialize request
        log(agent_id, "INFO", f"Sending initialize request...")
        proc.stdin.write(INITIALIZE_REQUEST.encode("utf-8"))
        await proc.stdin.drain()

        # Read response
        try:
            response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=PROBE_TIMEOUT)
            if response_line:
                decoded = response_line.decode("utf-8").strip()
                log(agent_id, "STDOUT", decoded)
                try:
                    parsed = json.loads(decoded)
                    result["acp_response"] = parsed
                    if "result" in parsed:
                        log(agent_id, "OK", f"Valid ACP initialize response received")
                    elif "error" in parsed:
                        log(agent_id, "WARN", f"ACP error response: {parsed['error']}")
                    else:
                        log(agent_id, "WARN", f"Unexpected JSON structure")
                except json.JSONDecodeError:
                    result["error"] = f"Non-JSON response: {decoded[:200]}"
                    log(agent_id, "ERROR", result["error"])
            else:
                result["error"] = "Empty response (stdout closed)"
                log(agent_id, "ERROR", result["error"])
        except asyncio.TimeoutError:
            result["error"] = "Timeout waiting for initialize response"
            log(agent_id, "ERROR", result["error"])

        # Cleanup
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                os.killpg(pgid, signal.SIGKILL)
                await proc.wait()
        except ProcessLookupError:
            pass

    except Exception as e:
        result["error"] = str(e)
        log(agent_id, "ERROR", result["error"])

    return result


async def main() -> None:
    requested = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    agents_to_probe = AGENTS
    if requested:
        agents_to_probe = [a for a in AGENTS if a[0] in requested]
        if not agents_to_probe:
            print(f"No matching agents. Available: {', '.join(a[0] for a in AGENTS)}")
            sys.exit(1)

    print(f"=== Nautex Agent ACP Diagnostic Probe ===\n")

    results = []
    for agent_id, executable, args, needs_port in agents_to_probe:
        result = await probe_agent(agent_id, executable, args, needs_port)
        results.append(result)
        print()

    # Summary
    print("=== Summary ===")
    for r in results:
        status = "NOT INSTALLED"
        if r["installed"]:
            if r["acp_response"] and "result" in r["acp_response"]:
                status = "OK"
            elif r["error"]:
                status = f"ERROR: {r['error'][:60]}"
            else:
                status = "UNKNOWN"
        print(f"  {r['agent_id']:18s} {status}")


if __name__ == "__main__":
    asyncio.run(main())
