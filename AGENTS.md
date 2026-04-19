# AGENTS.md

This file provides guidance to coding agents working in this repository.

## What this project is

`nautex-oss-util` is the Nautex open-source gateway node and MCP tooling. It
hosts a single ACP-to-Nautex bridge (`nautex gateway`) plus the CLI and MCP
server used by coding agents to talk to the Nautex backend. The hot code
path is under `src/nautex/gateway/`.

## Where to look

- `src/nautex/gateway/adapters/` — one concrete adapter (`ACPAgentAdapter`)
  plus per-agent subclasses for Claude Code, OpenCode, Codex, and others.
  See [`src/nautex/gateway/adapters/AGENTS.md`](src/nautex/gateway/adapters/AGENTS.md)
  for the per-agent compatibility matrix, credential sandboxing rules,
  and integration effort logs.
- `src/nautex/gateway/adapters/launch_config.py` — persistent config-file
  generation under `~/.nautex/configs/` with deterministic fingerprints.
- `src/nautex/gateway/protocol/` — synced with `nt-backend` via
  `make sync-agw-protocol`. Edit here, then sync.
- `scripts/` — the session-config probe and legacy raw-ACP probes.
  See [`scripts/AGENTS.md`](scripts/AGENTS.md) for the verification
  workflow (how and when to run the probe, how to read artifacts,
  when to add new scenarios).

## Verification

The primary verification tool is the session-config probe. Full guide in
[`scripts/AGENTS.md`](scripts/AGENTS.md). Quick reference:

| target | when | command |
|---|---|---|
| Session-config probe — single case | mid-iteration, fastest feedback | `make session-config-probe ARGS='--agent X --scenario Y'` |
| Session-config probe — full matrix | before opening a PR that touches adapters or protocol | `make session-config-probe ARGS='--all --timeout 90'` |
| ACP bridge + native binaries install check | after environment changes | `make install-acp-adapters` |
| Raw-ACP probe (new agent characterization only) | adding a new agent | `python scripts/probe_acp_agents.py <agent_id>` |
| Subsystem unit tests | when touching a specific subsystem | `pytest tests/gateway/test_<subsystem>.py` |

Any change under `src/nautex/gateway/adapters/`, `acp_client.py`, or
`launch_config.py` should run at minimum `make session-config-probe
ARGS='--agent <changed-agent>'` before commit. Full matrix before PR.

<!-- NAUTEX_SECTION_START -->

# Nautex MCP Integration

This project uses Nautex Model-Context-Protocol (MCP). Nautex manages requirements and task-driven LLM assisted development.

Whenever user requests to operate with nautex, the following applies:

- read full Nautex workflow guidelines from `.nautex/AGENTS.md`
- note that all paths managed by nautex are relative to the project root
- note primary workflow commands: `nautex__next_scope`, `nautex__tasks_update`
- NEVER edit files in `.nautex` directory

<!-- NAUTEX_SECTION_END -->
