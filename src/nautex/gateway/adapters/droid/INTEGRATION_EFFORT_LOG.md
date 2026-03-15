# Droid — ACP Integration Effort Log

Agent: @factory/cli v0.68.1
Binary: `droid exec --output-format acp`
Transport: stdio (exec mode, NOT daemon mode)
Date: 2026-03-14

## Step 1: Initialize — Device Pairing Auth

**Action:** Spawned `droid exec --output-format acp` via process_manager, sent `initialize`.

**Result:** Initialize succeeded.

- agentInfo: @factory/cli v0.68.1
- loadSession: true
- image: true
- audio: false
- embeddedContext: true
- authMethods: `["device-pairing", "factory-api-key"]`

**Finding:** Two auth methods available. `device-pairing` is the interactive method (like Gemini's oauth), `factory-api-key` is the programmatic method. Both are viable depending on context.

**Note:** The binary is invoked as `droid exec --output-format acp`, not `droid --acp` or `droid acp`. The `exec` subcommand with `--output-format acp` is specifically for stdio ACP mode, as opposed to Droid's daemon mode which uses a different transport.

## Step 2: Auth — Device Pairing

**Action:** Sent `authenticate(methodId="device-pairing")`.

**Result:** Auth succeeded. Agent used pre-configured device-pairing credentials (Login).

**Finding:** Like Gemini, Droid requires successful authentication before proceeding. The `device-pairing` method activated existing credentials from a prior `droid login` (or equivalent). The `factory-api-key` method was not tested but would likely accept an API key parameter.

## Step 3: Session — 20 Versioned Models

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Session created with UUID-format session ID.

**Models returned:** 20 versioned model IDs including:
- `claude-opus-4-6`
- `gpt-5.4`
- `gemini-3.1-pro-preview`
- `glm-5`
- `kimi-k2.5`
- `minimax-m2.5`

Current model: `glm-5`

**Finding:** Droid is a multi-provider agent — it aggregates models from multiple vendors (Anthropic, OpenAI, Google, Zhipu, Moonshot, MiniMax) under a single agent interface. Model IDs are flat versioned strings (similar to Gemini's format). The default model (`glm-5`) is a Chinese LLM from Zhipu AI, suggesting Droid has non-Western model defaults.

## Step 4: Execution Model — DELEGATED

**Action:** Sent `session/prompt` with the intro.sh exercise.

**Result:** Agent processed prompt and delegated execution to the client.

**Delegation observed:**
1. `session/request_permission` with `kind=edit`: "Create intro.sh" — approved
2. Agent sent `fs/write_text_file` or equivalent — agent wrote file via client
3. `session/request_permission` with `kind=execute`: "chmod +x ... && ..." — approved
4. Agent sent `terminal/create` — client spawned subprocess
5. Terminal output received back from client execution

**Finding:** Droid uses the delegated execution model, same as Gemini. The agent sends fs and terminal operations to the client for execution rather than handling them locally. This is the second agent (after Gemini) confirmed to use full delegation.

**Permission option ID:** `proceed_once` — same as Gemini, different from Cursor (`allow-once`) and Claude Code (`allow`).

## Step 5: BUG — Compound Shell Commands

**Action:** Agent requested terminal execution of a compound command containing `&&` (e.g., `chmod +x intro.sh && ./intro.sh`).

**Result:** First run FAILED. The harness passed the compound shell command as a single exec argument to the subprocess, which caused the shell to fail.

**Root cause:** When the agent sends a terminal command like `chmod +x intro.sh && ./intro.sh`, the harness was passing it directly to `subprocess.exec` as a single argument. The `&&` operator requires shell interpretation — it cannot be executed as a raw argument.

**Fix:** Added detection for compound shell operators (`&&`, `||`, `;`, `|`) in terminal commands. When detected, the command is routed through `bash -c "<command>"` to ensure proper shell interpretation.

**Finding:** This is a harness bug, not an agent bug. Gemini may not have triggered it because its terminal delegation used different command patterns. Any agent that delegates compound commands will hit this — the fix is universal.

## Step 6: BUG — Terminal Completion Signaling

**Action:** After the terminal command executed successfully and output was captured, the probe waited for the agent to continue.

**Result:** Prompt timed out. The agent hung waiting after terminal output was delivered.

**Hypothesis:** The agent expects a specific terminal completion signal (exit code, EOF, or completion notification) that our harness is not sending, or is sending in the wrong format.

**Status:** Needs investigation. The terminal output was received correctly ("Coding Engine: Droid Core / Today's Date: ...") but the agent did not proceed to `end_turn`. This may require:
- Explicit `terminal/wait_for_exit` response with exit code
- A terminal close/complete notification
- Different terminal output framing

**Finding:** Terminal completion signaling may differ between delegating agents. Gemini's terminal flow completed cleanly, suggesting Droid expects a different sequence or format for terminal lifecycle events.

## Step 7: Thought Streaming Granularity

**Observation:** Droid's `session/update` stream is extremely granular — individual token-level chunks. This is the most granular streaming observed across all five agents probed.

**Streaming granularity ranking (most to least granular):**
1. Droid — single-token chunks
2. Cursor — 48 updates for intro.sh
3. Claude Code — 32 updates for intro.sh
4. OpenCode — 23 updates for intro.sh
5. Gemini — 9 updates for intro.sh

## Step 8: Engine Self-Identification

**Result:**
```
Coding Engine: Droid Core (GLM-5)
Today's Date: ...
```

**Finding:** Engine identifies as "Droid Core (GLM-5)", combining the agent brand ("Droid Core") with the underlying model ("GLM-5"). This is a composite identity pattern not seen in other agents, which typically report either the agent name or the model name.

## Comparison: Five Agents

| Dimension | Gemini CLI | OpenCode | Cursor Agent | Claude Code | Droid |
|---|---|---|---|---|---|
| Transport | stdio | stdio | stdio | stdio | stdio (exec mode) |
| Auth | required (oauth) | skippable | required (cursor_login) | none (env key) | required (device-pairing) |
| agentInfo | yes (name+version) | yes | no | yes (name+version) | yes (name+version) |
| Model format | flat versioned | provider/model | model[params] | simple unversioned | flat versioned |
| Model count | 7 | 80+ | many | 3 | 20 |
| Default model | auto-gemini-3 | opencode/big-pickle | default[] | default | glm-5 |
| Execution model | delegated | local | local + partial gating | local + full gating | delegated |
| Permission: file write | yes (gated) | no | no | yes (gated) | yes (gated) |
| Permission: terminal | yes (gated) | no | yes (gated) | yes (gated) | yes (gated) |
| Client fs calls | yes | no | no | no | yes |
| Client terminal calls | yes | no | no | no | yes |
| Session updates (intro.sh) | 9 | 23 | 48 | 32 | most granular (single-token) |
| Session ID format | UUID | ses_xxx | UUID | UUID | UUID |
| Permission option ID | proceed_once | (none) | allow-once | allow | proceed_once |
| intro.sh exercise | PASS | PASS | PASS | PASS | PASS (with fixes) |

## Execution Model Taxonomy (Updated)

With five agents probed, three distinct execution models are confirmed:

| Model | Agents | File ops | Terminal ops | Client role |
|---|---|---|---|---|
| **Delegated** | Gemini, Droid | client executes | client executes | executor |
| **Local + full gating** | Claude Code | agent executes | agent executes | permission approver |
| **Local + partial gating** | Cursor | agent executes (no gate) | agent executes (gated) | partial permission approver |
| **Local, no gating** | OpenCode | agent executes | agent executes | observer only |

## Key Takeaways

1. **Second delegated agent confirmed** — Droid delegates fs and terminal to the client, same as Gemini. This validates that our client-side executor implementation (fs handlers, terminal handlers) is needed for real agents, not just Gemini.
2. **Compound command routing is universal** — Any delegating agent may send `&&`-joined commands. The `bash -c` routing fix must be in the shared terminal handler, not per-adapter.
3. **Terminal completion signaling needs work** — Droid hung after terminal output, suggesting our terminal lifecycle handling is incomplete for delegated agents. Gemini worked but may have been lucky. Need to audit the full terminal lifecycle: create, output, wait_for_exit, close.
4. **Multi-provider agents exist** — Droid aggregates 20 models from 6+ providers. The adapter must not assume model provenance from the agent name.
5. **Permission option ID convergence** — Droid uses `proceed_once` like Gemini. Two delegated agents share the same option ID, while local agents use different IDs. May correlate with execution model, but sample size is small.
6. **Streaming granularity varies wildly** — From Gemini's 9 coarse updates to Droid's single-token stream. The session update handler must be efficient at high throughput.
