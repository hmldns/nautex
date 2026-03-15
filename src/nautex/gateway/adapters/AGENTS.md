# Agent Adapters — Engineering Notes

## Integration Research Process

Each agent binary is treated as a black box implementing ACP to an unknown degree of completeness. We assume nothing about compliance — every behavior must be observed and documented empirically.

### Goal

Discover the right foundation for multi-agent support by probing each agent individually, documenting exact behaviors, and building a compatibility matrix from observed evidence. The matrix will expose which ACP features are reliably shared across agents and which require per-agent handling.

### Approach

ACP support across agents is likely a patchwork. Each implementation may:
- Interpret the spec differently
- Support a different subset of methods
- Handle auth, permissions, fs, and terminal in agent-specific ways
- Use different execution models (delegate to client vs execute locally)
- Return unexpected schemas or extra fields
- Fail silently in ways the spec doesn't account for

The probe process is designed to discover these dimensions systematically.

### Integration Effort Loop (per agent)

**1. Probe** — Run `python scripts/probe_acp_agents.py <agent_id>` against the real binary. Observe what happens at each ACP phase: initialize, authenticate, session/new, session/prompt, session/update stream.

**2. Document** — Record every observation in `adapters/<agent>/INTEGRATION_EFFORT_LOG.md`. Each step captures: what was sent, what was received, what broke, what was fixed. No assumptions — only evidence.

**3. Detect anomalies** — Compare observed behavior against the ACP spec and against other agents already probed. Note deviations: different field names, missing methods, unexpected error codes, schema mismatches with the SDK.

**4. Confirm generalities** — When a behavior matches another agent exactly, mark it as a confirmed shared trait. When it differs, mark it as agent-specific. This builds the compatibility matrix incrementally.

**5. Fix and re-probe** — Adjust the adapter or probe as needed, re-run until the full intro.sh exercise completes end-to-end. The exercise proves: file creation, file permissions, terminal execution, output capture.

**6. Update matrix** — Add the agent's row to the compatibility matrix with all observed dimensions.

**7. Reassess generalizations** — After each new agent is integrated, revisit all prior assumptions marked as "shared" in the matrix. A behavior confirmed across 2 agents may break on the 3rd. Any generalization baked into shared adapter code must be re-validated against the full set of completed agents. If a new agent contradicts a prior generalization, the shared code must be refactored to accommodate the variance — not the agent forced to comply.

### Dimensions to Probe

Each agent is evaluated across these dimensions:

| Dimension | What to observe |
|---|---|
| Initialize | protocolVersion accepted, agentInfo returned, agentCapabilities shape |
| Auth | authMethods available, which method works, pre-config required |
| Session | session/new params accepted, models returned, modes returned |
| Model switching | set_session_model supported, model IDs format |
| Execution model | Does agent delegate fs/terminal to client, or execute locally? |
| Permission gating | session/request_permission sent? What options? What response format? |
| File operations | fs/read_text_file and fs/write_text_file — delegated or local? |
| Terminal operations | terminal/create flow — delegated or local? Output format? |
| Session updates | What sessionUpdate types are emitted? Schema matches SDK? |
| Error behavior | How does agent report failures? Error codes? Retry patterns? |
| SDK compatibility | Does `agent-client-protocol` SDK work cleanly, or are there schema mismatches? |

### Compatibility Matrix — All 8 Agents (observed evidence, 2026-03-14)

| Dimension | Gemini | OpenCode | Cursor | Claude | Droid | Codex | Goose | Kiro |
|---|---|---|---|---|---|---|---|---|
| **intro.sh** | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Binary | gemini | opencode | cursor-agent | claude-agent-acp | droid | codex-acp | goose | kiro-cli |
| Version | 0.33.1 | 1.2.26 | — | 0.21.0 | 0.68.1 | 0.10.0 | 1.27.2 | 1.27.2 |
| Transport | stdio | stdio | stdio | stdio | stdio | stdio | stdio | stdio |
| agentInfo | yes | yes | **no** | yes | yes | yes | **no** | yes |
| **Execution** | delegated | local | local | local | delegated | partial | local | local |
| fs delegation | yes | no | no | no | yes | **yes** | no | no |
| terminal delegation | yes | no | no | no | yes | no | no | no |
| **Auth required** | yes | **no** | yes | **no** | yes | yes | yes | **no** |
| Auth method | oauth-personal | (fails, skip) | cursor_login | (none) | device-pairing | chatgpt | goose-provider | (fails, skip) |
| Credential source | ACP auth | internal file | ACP auth | env var | ACP auth | ACP auth | **env var** | internal |
| Needs full env | no | no | no | no | no | no | **yes** | no |
| **Perm: edit** | gated | none | none | gated | gated | gated | none | gated |
| **Perm: execute** | gated | none | gated | gated | gated | none | none | gated |
| Perm option ID | proceed_once | — | allow-once | allow | proceed_once | approved | — | allow_once |
| Perm kind field | edit/execute | — | execute | edit/execute | edit/execute | edit | — | **None** |
| Models count | 7 | 80+ | 23 | 3 | 20 | 22 | 9 | 7 |
| Model format | flat | provider/model | model[params] | simple | versioned | model/effort | flat | simple |
| Default model | auto-gemini-3 | big-pickle | default[] | default | glm-5 | gpt-5.4/xhigh | claude-sonnet-4-6 | auto |
| Session ID | UUID | ses_xxx | UUID | UUID | UUID | UUID | date-based | UUID |
| Session updates | 9 | 23 | 48 | 32 | — | 112 | 53 | 11 |
| embeddedContext | true | true | **false** | true | true | true | true | **false** |
| image | true | true | true | true | true | true | true | true |
| audio | **true** | false | false | false | false | false | false | false |
| loadSession | true | true | true | true | true | true | true | true |

### Execution Model Taxonomy (from evidence)

| Model | Agents | Description |
|---|---|---|
| **Fully delegated** | Gemini, Droid | Client handles all fs + terminal. Agent sends requests to client. |
| **Fully local** | OpenCode, Goose | Agent does everything. Zero client calls. Zero permissions. |
| **Local + permission gating** | Cursor, Claude, Kiro | Agent executes locally but gates some/all ops via permission requests. |
| **Partial delegation** | Codex | Delegates fs writes to client, executes terminal locally. |

### Confirmed Generalizations

These hold across all 8 agents:
- `protocolVersion: 1` (integer) — universal
- `loadSession: true` — universal
- `image: true` — universal
- stdio transport — universal (no agent required HTTP for ACP)
- `session/new` returns dynamic models — universal
- SDK `spawn_agent_process` works for all agents (with env fix for Goose)

### Agent-Specific Handling Required

These cannot be generalized — must be per-agent config:
- Auth method and whether it's required
- Credential source (ACP auth vs env var vs internal)
- Permission option IDs (5 different values across agents)
- Permission kind field (varies, one agent sends None)
- Model ID format (4 different formats)
- Whether to pass full host env (Goose only)
- ACP launch args (--acp, acp, exec --output-format acp, etc.)

### Effort Logs

- [`gemini/INTEGRATION_EFFORT_LOG.md`](gemini/INTEGRATION_EFFORT_LOG.md) — 7 steps. Delegated, auth required, full gating.
- [`opencode/INTEGRATION_EFFORT_LOG.md`](opencode/INTEGRATION_EFFORT_LOG.md) — 7 steps. Local, auth skippable, zero gates.
- [`cursor/INTEGRATION_EFFORT_LOG.md`](cursor/INTEGRATION_EFFORT_LOG.md) — Hybrid local, model=auto required, partial gating.
- [`claude/INTEGRATION_EFFORT_LOG.md`](claude/INTEGRATION_EFFORT_LOG.md) — Local + gating, no auth, env-based creds.
- [`droid/INTEGRATION_EFFORT_LOG.md`](droid/INTEGRATION_EFFORT_LOG.md) — Delegated like Gemini, terminal bash -c fix.
- [`codex/INTEGRATION_EFFORT_LOG.md`](codex/INTEGRATION_EFFORT_LOG.md) — Partial delegation, chatgpt auth, effort tiers.
- [`goose/INTEGRATION_EFFORT_LOG.md`](goose/INTEGRATION_EFFORT_LOG.md) — Local, env var bug, --with-builtin flag.
- [`kiro/INTEGRATION_EFFORT_LOG.md`](kiro/INTEGRATION_EFFORT_LOG.md) — Local + gating, auth skippable, kind=None anomaly.

## Credential Sandboxing

The process manager strips known sensitive environment variables from the host before spawning agent subprocesses. Only credentials explicitly provided via `AgentConfig.credentials` are injected.

**Current strip list** (`process_manager.py :: STRIPPED_ENV_KEYS`):
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

Extend as new agents are integrated.

## Permission Response Format

Confirmed critical across at least Gemini — must use:
```python
from acp.schema import AllowedOutcome
RequestPermissionResponse(
    outcome=AllowedOutcome(option_id="proceed_once", outcome="selected")
)
```
Bare `optionId` silently fails. Verify this holds for each new agent.

## QA Probe Tool

`scripts/probe_acp_agents.py` — drives real agent binaries end-to-end via the `agent-client-protocol` Python SDK.

```bash
python scripts/probe_acp_agents.py --list          # show agents + install status
python scripts/probe_acp_agents.py gemini_cli       # default intro.sh exercise
python scripts/probe_acp_agents.py gemini_cli -m gemini-2.5-flash  # specific model
python scripts/probe_acp_agents.py gemini_cli -t 120               # timeout
python scripts/probe_acp_agents.py gemini_cli -p "custom prompt"   # custom exercise
```
