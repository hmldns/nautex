# scripts — Session-Config Probe

This directory holds the headless verification tooling for the ACP adapter
layer. The centerpiece is the **session-config probe** — a scenario runner
that feeds a specific `AgentSessionConfig` (permissions, system prompt
extension, MCP servers) into each supported agent end-to-end through the
production `ACPAgentAdapter` path and writes a structured,
LLM-reviewable artifact tree.

It is the primary way we verify changes to anything under
`src/nautex/gateway/adapters/` before opening a PR.

The name distinguishes it from the lower-level **raw-ACP probes** under
`probes/`: those answer "does this binary speak ACP at all and how?", the
session-config probe answers "given `SessionConfigPayload` X, does the
production adapter path honor it?".

## Files

| file | role |
|---|---|
| `session_config_probe.py` | CLI entry — `--list`, `--agent`, `--scenario`, `--all`, `--out`, `--timeout`, `--keep-workdir`, `-v` |
| `session_config_scenarios.py` | `Scenario`, `CaseContext`, `Assertion` dataclasses + scenario registry |
| `session_config_runner.py` | Per-case async runner: spawn adapter, run prompt(s), capture signals, write artifacts, evaluate assertions |
| `probe_acp_agents.py` | Legacy raw-ACP probe (pre-adapter). Still useful when characterising a brand-new agent; do not duplicate its job in the session-config probe. |
| `probe_via_adapter.py` | 60-line reference for how the probe wires the adapter — keep it working as a canary. |
| `probes/` | The raw-ACP probe's `harness.py` (`ProbeClient`, `CallStats`), tmux orchestration scripts, and per-agent probe files. |

## What the probe does (and why this design)

Each `(agent, scenario)` case runs a real agent binary through
`create_adapter(...)` (the production factory) in a sandboxed temp
directory and records **every protocol signal**:

- `csus.jsonl` — every `ConsolidatedSessionUpdate` from both `system` and
  `prompt` phases, with ISO timestamps.
- `permissions.jsonl` — every `PermissionRequestPayload` + our
  `PermissionResponsePayload`, paired by `permission_id`.
- `stdout.log` — concatenated `AGENT_MESSAGE`/`AGENT_THOUGHT` text.
- `launch_cmd.json` — resolved executable, argv, extra env, prepared
  config paths (under `~/.nautex/configs/`), pid, acp session id.
- `config_used.json` — the `AgentSessionConfig` we fed in.
- `fs_diff.json` — created/modified/deleted paths vs the seeded workdir.
- `assertions.json` — scenario-specific pass/fail rows.
- `errors.log` — full tracebacks for any phase that raised (connect,
  prompt, disconnect), each tagged with the phase.
- `result.json` — one-line summary pointing at the above.

Top-level `index.json` aggregates every case with status + headline so a
reader can scan it first and drill into a failing case's artifact dir.

**Why this shape?** The old loop (restart AGW, click a tile, type in
Playwright, stare at logs) gave no reviewable trail. Agent-specific
quirks (Codex abort-on-reject, Claude reject_once being final, OpenCode
ignoring its own permission config in ACP mode) are easy to regress
silently. The probe replaces that loop with a single command that
produces evidence on disk.

## When to run it

- **Before committing** any change under `src/nautex/gateway/adapters/`,
  `src/nautex/gateway/acp_client.py`, `src/nautex/gateway/launch_config.py`,
  or the synced protocol files — run at minimum the scenarios that touch
  the subsystem you changed.
- **Before bumping** `@zed-industries/*-acp` or `@agentclientprotocol/*`
  packages (via `make install-acp-adapters`) — permission-option shapes
  and ACP response semantics change between versions; the probe catches
  it.
- **Before bumping** the `acp` Python SDK.
- **After a flaky end-to-end UI test** — rerun the relevant probe cases
  first; reproducing in the probe is ~10× faster than in Playwright.
- **Whenever you change** the tile-click `SessionConfigPayload` default in
  the backend (`nt-backend/.../agw/rest_routes.py`) — the probe's
  matching scenarios lock in the intended policy semantics.
- **Each CI run** (if/when wired) for the three primary agents:
  `claude_code`, `opencode`, `codex`.

## How to run

From `nautex-oss-util/`:

```bash
# Discover
make session-config-probe-list

# Fastest feedback — one case
make session-config-probe ARGS='--agent claude_code --scenario deny_write'

# All scenarios for one agent
make session-config-probe ARGS='--agent claude_code'

# Full matrix (claude_code × opencode × codex × every enabled scenario)
make session-config-probe ARGS='--all --timeout 90'

# Direct invocation (no make)
PYTHONPATH=src .venv/bin/python scripts/session_config_probe.py --agent codex \
    --scenario system_prompt_marker --timeout 60

# Debug: keep the sandbox tempdir so you can inspect what the agent saw
make session-config-probe ARGS='--agent opencode --scenario deny_write --keep-workdir -v'
```

Artifact root defaults to `~/.nautex/session_config_probe/<UTC-timestamp>/`.
Override with `--out <dir>`.

Exit code is 0 only when **every executed case passes**; any failure
makes the whole run exit 1 (useful for CI).

## How to read the artifacts

```bash
# Entry point — one row per case
jq '.' ~/.nautex/session_config_probe/<ts>/index.json

# Single case drill-down
ls  ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/
cat ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/result.json
cat ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/assertions.json
cat ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/fs_diff.json
cat ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/errors.log     # only on failures
head ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/csus.jsonl
jq '.' ~/.nautex/session_config_probe/<ts>/<agent>/<scenario>/permissions.jsonl
```

Typical diagnostic patterns:

- **File appeared despite a deny scope** → `fs_diff.created` is non-empty.
  Inspect `permissions.jsonl` — if empty, the agent didn't delegate
  permission via ACP for that tool; the enforcement must be at the
  config-generation layer or via sandboxing (OpenCode's case).
- **Turn cancelled unexpectedly** → `result.json.stop_reasons` contains
  `cancelled`; check `permissions.jsonl` for the option_id we selected,
  and `src/nautex/gateway/adapters/AGENTS.md` for that agent's reject
  semantics.
- **System prompt not honored** → `stdout.log` doesn't contain the
  scenario's marker. Check `launch_cmd.json` for whether the config
  file/flag was actually passed; some bridges ignore CLI flags
  (Claude's bridge reads `_meta.systemPrompt` over ACP, not
  `--append-system-prompt-file`, and we now prepend the extension into
  the first user turn as a fallback).
- **Rate-limit or auth failure** → `csus.jsonl` will have an
  `agent_error` entry with `error_code` and `error_detail`; the
  underlying cause is in the `data` JSON.

## When (and how) to update the probe

Update these files when the behavior you care about changes:

**`session_config_scenarios.py`** — add/edit scenarios when:
- A new agent quirk surfaces that existing scenarios wouldn't catch
  (e.g., a new ACP outcome kind, a new permission semantic).
- We change what the tile-click default policy is supposed to enforce.
- A new config field is added (skills, sandbox tier, etc.); add a
  scenario that fingerprints it.
- A published issue is reported against an adapter — capture it as a
  scenario so it becomes a permanent regression check.

Scenario contract:

```python
Scenario(
    id="...",                          # unique, kebab-or-snake
    description="...",                 # shows in --list
    build_config=lambda workdir: AgentSessionConfig(...),
    prompts=["..."],                   # one or more turns
    on_permission=policy_honoring,     # or always_approve / always_deny
    check=check_fn,                    # returns [Assertion(name, passed, detail)]
    skip_for={"opencode", ...},        # agents where scenario is N/A
    env_gate="PROBE_FORCE_...",        # optional — guard rare scenarios
)
```

**`session_config_runner.py`** — only touch when:
- A new `ConsolidatedSessionUpdate` kind needs special capture logic
  (e.g. structured tool_call fields) beyond the generic
  `csus.jsonl` dump.
- A new adapter callback is added to `ACPAgentAdapter` and scenarios
  need to observe it.
- Artifact layout evolves (add a new file per case). Keep
  `index.json`/`result.json` backward-compatible — `schema_version` is
  there for deliberate breaks.

**`session_config_probe.py`** — CLI flags, output formatting, agent list.
Keep it thin; logic belongs in the runner.

### Common verification mechanics (project-wide, beyond this probe)

| target | when | command |
|---|---|---|
| Python import / startup consistency | after any adapter or protocol change | `.venv/bin/python -c "import nautex.gateway.gateway_node_service"` |
| Session-config probe — single case | mid-iteration, quick loop | `make session-config-probe ARGS='--agent X --scenario Y'` |
| Session-config probe — full matrix | before PR | `make session-config-probe ARGS='--all --timeout 90'` |
| Protocol sync to backend | after editing `src/nautex/gateway/protocol/*.py` | run `make sync-agw-protocol` from `nt-backend/` |
| ACP bridge + native binaries | after environment changes | `make install-acp-adapters` (prints installed versions + discovered native binaries) |
| Raw-ACP probe (new agent characterization) | adding a new agent | `python scripts/probe_acp_agents.py <agent_id>` |
| Python tests (gateway subsystems) | when touching a specific subsystem | `pytest tests/gateway/test_<subsystem>.py` |

## Notes / gotchas

- The probe uses the **same** `~/.nautex/configs/cfg-launch-*` files
  the gateway uses — config fingerprint is deterministic on
  `(agent_id, cwd, config_json)`. Running the probe and the gateway
  simultaneously against the same cwd is fine (same files, same bytes)
  but concurrent writes of different configs for the same fingerprint
  would race. Don't.
- Some scenarios (`mcp_injection`) spawn subprocesses via `uvx` which
  may fetch packages from PyPI on first run; the per-prompt `--timeout`
  may need to be raised (90s+) on cold caches.
- `rate_limit_capture` is gated by `PROBE_FORCE_RATELIMIT=1` — it
  only demonstrates the error-capture path when the underlying account
  is actually limited; keep it skipped by default.
- Auth for Gemini/Cursor/Codex relies on the user's existing native
  credentials; the probe does **not** log in for you. Run the native
  binary at least once first.
