#!/usr/bin/env python3
"""Session-config probe — headless, full-fidelity scenario runner for ACPAgentAdapter.

Probes how a given `AgentSessionConfig` (permissions, system_prompt_extension,
mcp_servers) is actually honored by each agent, end-to-end via the production
adapter path (same factory, same launch config, same ~/.nautex/configs/ files),
WITHOUT the backend or frontend in the loop. Writes a structured artifact
tree for LLM/human review:

    <out>/
      index.json
      <agent>/<scenario>/
        result.json, assertions.json, csus.jsonl, permissions.jsonl,
        config_used.json, launch_cmd.json, fs_diff.json, stdout.log

Usage:
    python scripts/session_config_probe.py --list
    python scripts/session_config_probe.py --agent claude_code
    python scripts/session_config_probe.py --agent codex --scenario deny_write
    python scripts/session_config_probe.py --all
    python scripts/session_config_probe.py --all --out ./probe_runs/$(date +%s)/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from nautex.gateway.config import available_supported_agents  # noqa: E402

from session_config_runner import CaseRunner, binary_available  # noqa: E402
from session_config_scenarios import (  # noqa: E402
    ALL_SCENARIOS,
    SCENARIOS_BY_ID,
    Scenario,
    scenario_is_enabled,
)


_DEFAULT_AGENTS = ("claude_code", "opencode", "codex")
_ARTIFACT_ROOT_NAME = "session_config_probe"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="List agents and scenarios then exit.")
    p.add_argument("--agent", default=None, help="Agent id to run. Omit with --all for the default three.")
    p.add_argument("--scenario", default=None, help="Scenario id to run (defaults to all enabled).")
    p.add_argument("--all", action="store_true", help="Run default three agents × all enabled scenarios.")
    p.add_argument("--out", default=None,
                   help=f"Output directory for artifacts (default ~/.nautex/{_ARTIFACT_ROOT_NAME}/<ts>/).")
    p.add_argument("--timeout", type=float, default=60.0, help="Per-prompt timeout, seconds.")
    p.add_argument("--keep-workdir", action="store_true", help="Keep per-case temp dirs for debugging.")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable INFO logging from the adapter stack.")
    return p.parse_args()


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _list_and_exit() -> None:
    print("Agents (from SUPPORTED_AGENTS):")
    for aid, reg in available_supported_agents().items():
        marker = "OK" if binary_available(aid) else "NO BIN"
        print(f"  [{marker:>6}] {aid:<20} {reg.executable}")
    print("\nScenarios:")
    for sc in ALL_SCENARIOS:
        gate = f" (gated by ${sc.env_gate})" if sc.env_gate else ""
        skips = f" skip_for={sorted(sc.skip_for)}" if sc.skip_for else ""
        print(f"  {sc.id:<28} — {sc.description}{gate}{skips}")


def _default_out_dir() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / ".nautex" / _ARTIFACT_ROOT_NAME / ts


def _select_scenarios(scenario_id: Optional[str]) -> List[Scenario]:
    if scenario_id is None:
        return [s for s in ALL_SCENARIOS if scenario_is_enabled(s)]
    sc = SCENARIOS_BY_ID.get(scenario_id)
    if sc is None:
        raise SystemExit(f"unknown scenario: {scenario_id}")
    return [sc]


def _select_agents(args: argparse.Namespace) -> List[str]:
    if args.agent:
        return [args.agent]
    if args.all:
        return list(_DEFAULT_AGENTS)
    # Default when neither --agent nor --all given: also the default trio.
    return list(_DEFAULT_AGENTS)


def _print_row(row: dict) -> None:
    status_badge = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}.get(row["status"], row["status"])
    # flush=True so progress is visible when stdout is piped or redirected.
    print(f"  {status_badge:<4}  {row['agent']:<14} {row['scenario']:<26} {row['headline']}", flush=True)


async def _run_all(args: argparse.Namespace) -> int:
    agents = _select_agents(args)
    scenarios = _select_scenarios(args.scenario)

    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    all_rows: List[dict] = []
    fail = False

    print(f"probe out: {out_dir}", flush=True)
    print("", flush=True)

    for agent_id in agents:
        if not binary_available(agent_id):
            row = {
                "agent": agent_id, "scenario": "*", "status": "skip",
                "headline": "binary not on PATH",
                "artifacts": "",
            }
            all_rows.append(row)
            _print_row(row)
            continue

        for sc in scenarios:
            if agent_id in sc.skip_for:
                row = {
                    "agent": agent_id, "scenario": sc.id, "status": "skip",
                    "headline": "skip_for includes this agent",
                    "artifacts": "",
                }
                all_rows.append(row)
                _print_row(row)
                continue

            print(f"  ....  {agent_id:<14} {sc.id:<26} running...", flush=True)
            runner = CaseRunner(
                agent_id=agent_id,
                scenario=sc,
                out_dir=out_dir,
                timeout_s=args.timeout,
                keep_workdir=args.keep_workdir,
            )
            try:
                result = await runner.run()
            except Exception as e:
                result = {
                    "agent": agent_id, "scenario": sc.id, "status": "fail",
                    "headline": f"runner error: {type(e).__name__}: {e}",
                    "error": str(e),
                }
            result["artifacts"] = f"{agent_id}/{sc.id}/"
            all_rows.append(result)
            _print_row(result)
            if result["status"] == "fail":
                fail = True

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    totals = {
        "cases": len(all_rows),
        "passed": sum(1 for r in all_rows if r["status"] == "pass"),
        "failed": sum(1 for r in all_rows if r["status"] == "fail"),
        "skipped": sum(1 for r in all_rows if r["status"] == "skip"),
    }
    index = {
        "schema_version": 1,
        "started_at": started,
        "finished_at": finished,
        "cases": all_rows,
        "totals": totals,
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2, default=str), encoding="utf-8")

    print("", flush=True)
    print(f"totals: {totals}", flush=True)
    print(f"index:  {out_dir / 'index.json'}", flush=True)

    return 1 if fail else 0


def main() -> int:
    args = _parse_args()
    if args.list:
        _list_and_exit()
        return 0
    _configure_logging(args.verbose)
    return asyncio.run(_run_all(args))


if __name__ == "__main__":
    raise SystemExit(main())
