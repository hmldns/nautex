# Codex — ACP Integration Effort Log

Agent: codex-acp v0.10.0 (@zed-industries/codex-acp)
Binary: `codex-acp` (Zed JS wrapper)
Transport: stdio
Date: 2026-03-14

## Step 1: Binary Discovery — Rust Crate Failed, JS Wrapper Works

**Action:** Attempted to compile `cola-io/codex-acp` (Rust crate).

**Result:** Compilation failed.

**Action:** Installed `@zed-industries/codex-acp` v0.10.0 via `npm install -g @zed-industries/codex-acp`.

**Result:** Binary `codex-acp` available and functional.

**Finding:** Similar to Claude Code, the working ACP binary comes from Zed's JS wrapper ecosystem (`@zed-industries`), not from the upstream vendor directly. The Rust implementation (`cola-io/codex-acp`) is not viable at this time.

## Step 2: Initialize — Three Auth Methods

**Action:** Spawned `codex-acp` via process_manager, sent `initialize`.

**Result:** Initialize succeeded.

- agentInfo: codex-acp v0.10.0
- loadSession: true
- image: true
- audio: false
- embeddedContext: true
- authMethods: `["chatgpt", "codex-api-key", "openai-api-key"]`

**Finding:** Three auth methods available — the most of any agent probed. `chatgpt` is the interactive OAuth-style method (Login with ChatGPT), while `codex-api-key` and `openai-api-key` are programmatic methods. This gives users flexibility: consumer login, Codex-specific key, or general OpenAI key.

## Step 3: Auth — ChatGPT Login

**Action:** Sent `authenticate(methodId="chatgpt")`.

**Result:** Auth succeeded. Agent used pre-configured ChatGPT credentials (Login with ChatGPT).

**Finding:** Like Gemini and Droid, Codex requires successful authentication before proceeding. The `chatgpt` method activated existing credentials from a prior login. The two API key methods were not tested but would accept key parameters directly.

## Step 4: Session — 22 Models with Effort Tiers

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Session created with UUID-format session ID.

**Models returned:** 22 models with effort tier variants:
- `gpt-5.4/low`, `gpt-5.4/medium`, `gpt-5.4/high`, `gpt-5.4/xhigh`
- `gpt-5.3-codex/*` (low through xhigh)
- `gpt-5.2-codex/*` (low through xhigh)
- `gpt-5.2/*` (low through xhigh)
- `gpt-5.1-codex-max/*` (low through xhigh)
- `gpt-5.1-codex-mini/*` (low through xhigh)

Current model: `gpt-5.4/xhigh`

**Finding:** Codex introduces a fifth model ID format: `model/effort-tier`. This is distinct from Gemini's flat versioned IDs, OpenCode's `provider/model` namespaced IDs, Cursor's `model[params]` annotated IDs, and Claude Code's simple unversioned names. The `/low` through `/xhigh` suffix controls reasoning effort, similar in concept to OpenCode's quality tiers (`/low`, `/high`, `/max`) but with a different semantic (effort vs quality) and more granularity (4 tiers vs 3). Default is the highest tier (`gpt-5.4/xhigh`).

## Step 5: Execution Model — PARTIAL DELEGATION

**Action:** Sent `session/prompt` with the intro.sh exercise.

**Result:** Agent processed prompt with a hybrid execution model.

**Delegation observed:**
1. **File write** — delegated to client via `fs/write_text_file` (1 client write call)
2. **Permission gate** — `session/request_permission` with `kind=edit`: 1 permission request for the file edit
3. **Terminal execute** — executed locally by the agent (0 client terminal calls, 0 terminal permission requests)

**Client call stats:** 0 fs reads, 1 fs write, 0 terminal creates, 1 permission request.

**Finding:** Codex uses a unique PARTIAL DELEGATION model — the inverse of Cursor's. Cursor executes files locally (no gate) but gates terminal; Codex delegates file writes to the client (gated) but executes terminal commands locally (no gate, no permission). This is the fifth execution model variant discovered.

**Permission option ID:** `approved`

## Step 6: Permission Option ID — "approved"

**Action:** Responded to the file edit permission request with `AllowedOutcome`.

**Result:** Permission approved successfully. Agent proceeded with file creation via client delegation.

**Permission option ID:** `approved`

**Finding:** Fifth permission option ID observed across agents:
- Gemini: `proceed_once`
- Cursor: `allow-once`
- Claude Code: `allow`
- Droid: `proceed_once`
- Codex: `approved`

The `approved` option (past tense, no suffix) suggests a definitive grant semantic. Every agent uses a different vocabulary for the same concept. Permission option IDs absolutely cannot be hardcoded — must be read from the permission request options.

## Step 7: Full End-to-End Success

**Action:** Full probe completed end-to-end.

1. `initialize` — codex-acp v0.10.0, 3 auth methods
2. `authenticate` — chatgpt method, cached creds
3. `session/new` — session created, 22 models available, current=gpt-5.4/xhigh
4. `session/prompt` — agent processes prompt
5. `session/request_permission` (edit) — approved with `approved`
6. Agent delegates file write via `fs/write_text_file` — client writes to disk
7. Agent executes terminal command locally (no delegation, no permission)
8. `session/update` stream — 112 updates with final output
9. `stopReason: end_turn`

**Result:**
```
Coding engine: Codex
Today's Date: ...
```

intro.sh created on disk, executable, content correct.

## Step 8: Session Update Volume

112 session updates observed for the intro.sh exercise — the highest of all agents probed by a wide margin.

**Streaming granularity ranking (most to least granular):**
1. Codex — 112 updates for intro.sh
2. Droid — single-token chunks (most granular per-token)
3. Cursor — 48 updates for intro.sh
4. Claude Code — 32 updates for intro.sh
5. OpenCode — 23 updates for intro.sh
6. Goose — 53 updates for intro.sh
7. Kiro — 11 updates for intro.sh (most efficient)
8. Gemini — 9 updates for intro.sh

**Finding:** Codex produces the most discrete session update events of any agent. The session update handler must be optimized for high throughput to avoid backpressure on the update stream.

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

1. **Fifth execution model variant** — Codex partially delegates file writes to the client while executing terminal commands locally without permission. This is the inverse of Cursor's pattern (local files, gated terminal). The adapter must handle outbound `fs/write_text_file` client calls without expecting terminal delegation.
2. **Effort tiers are a new model dimension** — The `model/effort-tier` format (low/medium/high/xhigh) controls reasoning effort per request. This is conceptually similar to OpenCode's quality tiers but uses a different naming convention and has 4 levels instead of 3.
3. **Three auth methods** — Codex offers the most authentication flexibility. The adapter should prefer `chatgpt` for interactive use and `codex-api-key` or `openai-api-key` for programmatic/CI use.
4. **Highest session update volume** — 112 updates for intro.sh is 2.3x the next highest (Cursor at 48). Session update processing must not be a bottleneck.
5. **Zed wrapper pattern confirmed** — Like Claude Code, the working binary comes from `@zed-industries`, not the upstream vendor. Two of eight agents now use Zed wrappers as their ACP interface.
6. **Permission option ID diversity continues** — `approved` is the fifth distinct option ID. The set is now: `proceed_once`, `allow-once`, `allow`, `approved`, `allow_once`, and none. Dynamic reading from permission options is mandatory.
