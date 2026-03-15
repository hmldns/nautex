# Kiro CLI — ACP Integration Effort Log

Agent: Kiro CLI Agent v1.27.2
Binary: `kiro-cli acp`
Transport: stdio
Date: 2026-03-14

## Step 1: Initialize — Familiar Capabilities, No Embedded Context

**Action:** Spawned `kiro-cli acp` via process_manager, sent `initialize`.

**Result:** Initialize succeeded.

- agentInfo: Kiro CLI Agent v1.27.2
- loadSession: true
- image: true
- audio: false
- embeddedContext: false
- authMethods: `["kiro-login"]`

**Finding:** Kiro is the only agent with `embeddedContext: false`. All other seven agents report `embeddedContext: true`. This means Kiro does not support receiving additional context alongside prompts via the ACP embedded context mechanism. The adapter must not attempt to pass embedded context to Kiro sessions — it will either be ignored or cause an error.

**Note:** Installed via curl script from `kiro.dev`. The binary is `kiro-cli` with the `acp` subcommand for ACP stdio mode.

## Step 2: Auth — Method Not Found (Skippable)

**Action:** Sent `authenticate(methodId="kiro-login")`.

**Result:** Error: "Method not found".

**Action:** Skipped auth, proceeded to `session/new`.

**Result:** Session created successfully without authentication.

**Finding:** Kiro's auth pattern matches OpenCode: the ACP `authenticate` method is declared but fails when called. The agent uses internal credentials instead. This is the third agent (after OpenCode and Goose) where auth is effectively skippable. The adapter must handle auth failure gracefully and proceed without it.

**Hypothesis:** Kiro uses AWS-based internal credentials (given its Amazon/AWS origin). The `kiro-login` method may be intended for future interactive login flows that are not yet implemented in the CLI variant.

## Step 3: Session — 7 Simple Model IDs

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Session created with UUID-format session ID.

**Models returned:** 7 models with simple IDs:
- `auto` (current/default)
- `claude-sonnet-4.5`
- `claude-sonnet-4`
- `claude-haiku-4.5`
- `deepseek-3.2`
- `minimax-m2.1`
- `qwen3-coder-next`

Current model: `auto`

**Finding:** Kiro is a multi-provider agent like Droid — it offers models from Anthropic (Claude), DeepSeek, MiniMax, and Alibaba (Qwen) under a single interface. Model IDs are simple flat strings without namespacing, tiers, or annotations. The `auto` default model (like Gemini's `auto-gemini-3` and Claude Code's `default`) delegates model selection to the agent's internal routing logic. With 7 models, Kiro matches Gemini CLI for the smallest catalog alongside the most diverse provider mix.

## Step 4: Execution Model — LOCAL with Full Permission Gating

**Action:** Sent `session/prompt` with the intro.sh exercise.

**Result:** Agent processed prompt locally. Two permission gates were encountered.

**Permissions observed:**
1. **File write** — `session/request_permission` with `kind=None`: permission for file edit
2. **Terminal execute** — `session/request_permission` with `kind=None`: permission for command execution

**Client call stats:** 0 fs reads, 0 fs writes, 0 terminal creates, 2 permission requests.

**Finding:** Kiro uses the same execution model as Claude Code: local execution with full permission gating on both file writes and terminal commands. However, there is a notable anomaly in the permission requests.

## Step 5: Permission Anomaly — kind=None

**Action:** Examined the permission request payloads.

**Result:** Both permission requests have `kind=None` instead of the expected `kind=edit` or `kind=execute` labels.

**Finding:** Kiro does not populate the `kind` field in its permission requests. This is unique among all agents that use permission gating:
- Claude Code: `kind=edit` and `kind=execute`
- Cursor: `kind=execute`
- Gemini: `kind=edit` and `kind=execute`
- Droid: `kind=edit` and `kind=execute`
- Codex: `kind=edit`
- Kiro: `kind=None` for both

The adapter cannot rely on `kind` to distinguish between file and terminal permissions for Kiro. Permission type must be inferred from the description text or treated as opaque. The permission handler should approve based on the option ID regardless of kind.

## Step 6: Permission Option ID — "allow_once"

**Action:** Responded to both permission requests with `AllowedOutcome`.

**Result:** Both permissions approved successfully. Agent proceeded with file creation and terminal execution.

**Permission option ID:** `allow_once`

**Finding:** Sixth permission option ID variant observed across agents:
- Gemini: `proceed_once`
- Cursor: `allow-once` (hyphenated)
- Claude Code: `allow`
- Droid: `proceed_once`
- Codex: `approved`
- Kiro: `allow_once` (underscored)

Note the subtle difference between Cursor's `allow-once` (hyphen) and Kiro's `allow_once` (underscore). These are distinct string values that would fail if confused. The growing diversity of option IDs reinforces that dynamic reading from permission request options is the only viable approach.

## Step 7: Full End-to-End Success

**Action:** Full probe completed end-to-end.

1. `initialize` — Kiro CLI Agent v1.27.2, 1 auth method
2. `authenticate` — kiro-login method, "Method not found" (skipped)
3. `session/new` — session created, 7 models available, current=auto
4. `session/prompt` — agent processes prompt
5. `session/request_permission` (kind=None, file edit) — approved with `allow_once`
6. Agent writes file locally (no client fs call)
7. `session/request_permission` (kind=None, terminal execute) — approved with `allow_once`
8. Agent runs command locally (no client terminal call)
9. `session/update` stream — 11 updates with final output
10. `stopReason: end_turn`

**Result:**
```
Kiro
[date output]
```

intro.sh created on disk, executable, content correct.

**Observation:** Kiro's intro.sh output is minimal — just "Kiro" and the date, without the "Coding engine:" prefix used by most other agents. The engine self-identification is the most terse of all agents. This does not affect functionality but shows variance in how agents interpret the exercise prompt.

## Step 8: Session Update Volume — Most Efficient

11 session updates observed for the intro.sh exercise — the lowest of all agents probed.

**Streaming granularity ranking (most to least granular):**
1. Codex — 112 updates for intro.sh
2. Droid — single-token chunks (most granular per-token)
3. Goose — 53 updates for intro.sh
4. Cursor — 48 updates for intro.sh
5. Claude Code — 32 updates for intro.sh
6. OpenCode — 23 updates for intro.sh
7. Kiro — 11 updates for intro.sh
8. Gemini — 9 updates for intro.sh

**Finding:** Kiro is the most efficient agent in terms of session update volume — it produces only 11 updates to complete the full exercise, just above Gemini's 9. This suggests Kiro batches its streaming output into larger chunks rather than emitting per-token updates. The session update handler will have minimal throughput concerns with Kiro.

## Comparison: Eight Agents

| Dimension | Gemini CLI | OpenCode | Cursor Agent | Claude Code | Droid | Codex | Goose | Kiro |
|---|---|---|---|---|---|---|---|---|
| Transport | stdio | stdio | stdio | stdio | stdio (exec mode) | stdio | stdio | stdio |
| Auth | required (oauth) | skippable | required (cursor_login) | none (env key) | required (device-pairing) | required (chatgpt) | skippable (env key) | skippable (internal creds) |
| Auth methods | 1 | 1 | 1 | 0 | 2 | 3 | 1 | 1 |
| agentInfo | yes (name+version) | yes | no | yes (name+version) | yes (name+version) | yes (name+version) | no | yes (name+version) |
| Model format | flat versioned | provider/model | model[params] | simple unversioned | flat versioned | model/effort-tier | simple IDs | simple IDs |
| Model count | 7 | 80+ | many | 3 | 20 | 22 | 9 | 7 |
| Default model | auto-gemini-3 | opencode/big-pickle | default[] | default | glm-5 | gpt-5.4/xhigh | claude-sonnet-4-6 | auto |
| Execution model | delegated | local | local + partial gating | local + full gating | delegated | partial delegation (inverse) | local | local + full gating |
| Permission: file write | yes (gated) | no | no | yes (gated) | yes (gated) | yes (gated + delegated) | no | yes (gated) |
| Permission: terminal | yes (gated) | no | yes (gated) | yes (gated) | yes (gated) | no | no | yes (gated) |
| Client fs calls | yes | no | no | no | yes | yes (write only) | no | no |
| Client terminal calls | yes | no | no | no | yes | no | no | no |
| Session updates (intro.sh) | 9 | 23 | 48 | 32 | single-token | 112 | 53 | 11 |
| Session ID format | UUID | ses_xxx | UUID | UUID | UUID | UUID | date-based | UUID |
| Permission option ID | proceed_once | (none) | allow-once | allow | proceed_once | approved | (none) | allow_once |
| intro.sh exercise | PASS | PASS | PASS | PASS | PASS (with fixes) | PASS | PASS | PASS |
| embeddedContext | true | true | true | true | true | true | true | false |

## Execution Model Taxonomy (Updated — 8 Agents)

| Model | Agents | File ops | Terminal ops | Client role |
|---|---|---|---|---|
| **Delegated** | Gemini, Droid | client executes | client executes | executor |
| **Partial delegation (fs)** | Codex | client executes (gated) | agent executes (no gate) | partial executor |
| **Local + full gating** | Claude Code, Kiro | agent executes | agent executes | permission approver |
| **Local + partial gating** | Cursor | agent executes (no gate) | agent executes (gated) | partial permission approver |
| **Local, no gating** | OpenCode, Goose | agent executes | agent executes | observer only |

## Key Takeaways

1. **embeddedContext=false is unique** — Kiro is the only agent that does not support embedded context. The adapter must skip embedded context injection for Kiro sessions. This may limit certain features that rely on passing additional context alongside prompts.
2. **kind=None in permissions** — Kiro does not label its permission requests with `kind=edit` or `kind=execute`. The permission handler must not assume `kind` is populated and should approve based on option ID alone, or infer the permission type from the description text.
3. **Most efficient streaming** — 11 updates for intro.sh is the second lowest (after Gemini's 9). Kiro batches output aggressively, which is beneficial for network efficiency but means progress reporting may appear less granular to the user.
4. **Subtle option ID variants** — `allow_once` (underscore) vs Cursor's `allow-once` (hyphen). String comparison for permission option IDs must be exact — no normalization or fuzzy matching.
5. **Multi-provider with auto routing** — Kiro's `auto` default model and mix of Anthropic/DeepSeek/MiniMax/Qwen models suggests server-side model routing. The adapter should not assume which underlying model is being used when `auto` is selected.
6. **Terse self-identification** — Kiro's intro.sh output omits the "Coding engine:" prefix, just outputting "Kiro". The adapter should not parse engine identity from intro.sh output — it's not standardized across agents.
