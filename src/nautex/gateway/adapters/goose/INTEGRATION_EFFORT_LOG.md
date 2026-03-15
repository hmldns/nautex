# Goose — ACP Integration Effort Log

Agent: Block Goose v1.27.2
Binary: `goose acp --with-builtin developer`
Transport: stdio
Date: 2026-03-14

## Step 1: Initialize — No agentInfo

**Action:** Spawned `goose acp --with-builtin developer` via process_manager, sent `initialize`.

**Result:** Initialize succeeded.

- agentInfo: NOT returned (no agentInfo in init response)
- loadSession: true
- image: true
- audio: false
- embeddedContext: true
- authMethods: `["goose-provider"]`

**Finding:** Goose is the second agent (after Cursor) to not return `agentInfo` in the initialize response. The adapter must handle missing agent metadata gracefully. The `--with-builtin developer` flag is required to enable file and terminal tools — without it, Goose lacks the ability to perform the intro.sh exercise.

**Note:** Goose is developed by Block (formerly Square). Installed via curl script from the official site.

## Step 2: Auth — Provider Configuration

**Action:** Sent `authenticate(methodId="goose-provider")`.

**Result:** Auth succeeded. Agent used pre-configured provider credentials (Configure Provider).

**Finding:** Goose's auth method is labeled "Configure Provider" — it selects which LLM provider to use for inference. This is a different semantic than other agents where auth grants access to the agent itself. In Goose's case, the agent is open source and free; auth configures which backend model provider powers it.

## Step 3: CRITICAL BUG — API Key Stripped from Environment

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Session creation silently failed after 15-second timeout.

**Root cause:** The SDK's `default_environment()` helper strips `ANTHROPIC_API_KEY` from the subprocess environment (it's in our `STRIPPED_ENV_KEYS` list). Goose reads its API key directly from the environment, not through ACP authentication. Unlike Claude Code which also uses `ANTHROPIC_API_KEY` from env, Goose does not surface this as a missing-auth error — it silently hangs on `session/new`.

**Fix:** Pass `env=dict(os.environ)` to `spawn_agent_process` for Goose, bypassing the credential sandboxing that strips `ANTHROPIC_API_KEY`. Alternatively, add Goose-specific credential injection similar to Claude Code's handling.

**Finding:** This is the same class of issue as Claude Code (env-based auth), but worse because Goose fails silently instead of reporting an error. The credential sandboxing logic in `process_manager.py` must be agent-aware: agents that use env-based API keys (Claude Code, Goose) need those keys preserved, while agents that should not inherit host credentials still need them stripped.

## Step 4: Session — 9 Anthropic Models

**Action:** After fixing the API key issue, sent `session/new` again.

**Result:** Session created with date-based session ID format (`20260315_10`).

**Models returned:** 9 Anthropic models:
- `claude-sonnet-4-6` (current/default)
- `claude-opus-4-6`
- `claude-opus-4-5`
- `claude-sonnet-4-5`
- `claude-sonnet-4`
- `claude-haiku-4.5`
- Additional older sonnet variants

Current model: `claude-sonnet-4-6`

**Finding:** Goose is exclusively powered by Anthropic models (when configured with Anthropic provider). Model IDs are simple flat strings without version suffixes, tiers, or annotations — similar to Claude Code's minimalist format but with more specific names. The date-based session ID format (`20260315_10`) is unique among all agents — neither UUID nor `ses_` prefixed.

## Step 5: Execution Model — LOCAL, Zero Delegation

**Action:** Sent `session/prompt` with the intro.sh exercise.

**Result:** Agent processed prompt entirely locally. Zero client calls, zero permissions.

**Client call stats:** 0 fs reads, 0 fs writes, 0 terminal creates, 0 permission requests.

**Finding:** Goose executes everything locally with no delegation and no permission gating — identical to OpenCode's execution model. The agent reads files, writes files, and runs terminal commands directly on disk without asking the client for permission or execution. This is the "observer only" client role — we learn about results purely through `session/update` notifications.

## Step 6: No Permission Gating

**Finding:** Goose sent zero `session/request_permission` notifications throughout the entire exercise. All tool executions happened silently.

This means for Goose:
- Our `request_permission` handler is never called
- Our `write_text_file` / `create_terminal` handlers are never called
- We observe results purely through `session/update` notifications

This matches OpenCode's behavior exactly. Two of eight agents now operate with zero permission gating.

## Step 7: Full End-to-End Success

**Action:** Full probe completed end-to-end (after API key fix).

1. `initialize` — Block Goose v1.27.2 (no agentInfo), 1 auth method
2. `authenticate` — goose-provider method, cached provider config
3. `session/new` — session created, 9 models available, current=claude-sonnet-4-6
4. `session/prompt` — agent processes prompt
5. Agent writes file locally (no delegation, no permission)
6. Agent executes terminal command locally (no delegation, no permission)
7. `session/update` stream — 53 updates with final output
8. `stopReason: end_turn`

**Result:**
```
Coding Engine: goose (by Block)
Today's Date: ...
```

intro.sh created on disk, executable, content correct.

**Observation:** Engine identifies itself as "goose (by Block)", attributing to the corporate parent. This is distinct from other agents which identify by model name (Claude Code: "Claude Opus 4.6") or agent name (Gemini: "Gemini CLI").

## Step 8: Session Update Volume

53 session updates observed for the intro.sh exercise. This places Goose in the middle of the streaming granularity spectrum.

**Streaming granularity ranking (most to least granular):**
1. Codex — 112 updates for intro.sh
2. Droid — single-token chunks (most granular per-token)
3. Goose — 53 updates for intro.sh
4. Cursor — 48 updates for intro.sh
5. Claude Code — 32 updates for intro.sh
6. OpenCode — 23 updates for intro.sh
7. Kiro — 11 updates for intro.sh
8. Gemini — 9 updates for intro.sh

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
| Execution model | delegated | local | local + partial gating | local + full gating | delegated | partial delegation (inverse) | local | local + permission gating |
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

1. **CRITICAL: Silent failure from credential sandboxing** — Goose reads `ANTHROPIC_API_KEY` from the environment, and our `STRIPPED_ENV_KEYS` removes it. Unlike Claude Code (which also needs env keys but at least surfaces auth errors), Goose fails silently with a 15-second timeout on `session/new`. The process_manager must be updated to preserve API keys for agents that require them in the environment.
2. **Second "observer only" agent** — Goose matches OpenCode's execution model exactly: local execution, zero delegation, zero permissions. The adapter's client-side handlers (fs, terminal, permission) are never invoked.
3. **No agentInfo is a real pattern** — Two of eight agents (Goose and Cursor) do not return `agentInfo`. The adapter must treat it as optional and use fallback identification (binary name, version from other sources).
4. **Date-based session IDs** — Third session ID format discovered: date-based (`20260315_10`), alongside UUID and `ses_` prefixed. Session ID format cannot be assumed.
5. **`--with-builtin developer` flag is required** — Without this flag, Goose lacks file and terminal tools. The adapter must include this flag in the spawn command, or the intro.sh exercise (and any real work) will fail.
6. **Auth semantic differs** — Goose's "Configure Provider" auth selects a model backend, not access to the agent. This is conceptually different from all other agents where auth grants agent access. The adapter should treat Goose auth as provider configuration rather than credential activation.
