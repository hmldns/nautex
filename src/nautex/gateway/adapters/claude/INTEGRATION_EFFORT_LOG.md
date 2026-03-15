# Claude Code — ACP Integration Effort Log

Agent: @zed-industries/claude-agent-acp v0.21.0
Binary: `claude-agent-acp` (Zed wrapper)
Transport: stdio
Date: 2026-03-14

## Step 1: Initialize — No Auth Needed

**Action:** Spawned `claude-agent-acp` via process_manager, sent `initialize`.

**Result:** Initialize succeeded immediately.

- agentInfo: @zed-industries/claude-agent-acp v0.21.0
- loadSession: true
- image: true
- audio: false
- embeddedContext: true
- authMethods: empty — no auth methods returned

**Finding:** Claude Code uses `ANTHROPIC_API_KEY` from the environment. No ACP-level authentication is needed. This is a third auth pattern: Gemini requires ACP auth (oauth), OpenCode has ACP auth that fails and can be skipped, Cursor requires ACP auth (cursor_login), and Claude Code bypasses ACP auth entirely via environment variable.

**Note:** The binary is `claude-agent-acp`, which is a Zed-maintained wrapper (`@zed-industries/claude-agent-acp`), not Anthropic's `claude` CLI directly. This wrapper exposes ACP over stdio.

## Step 2: Session — Simple Model IDs

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Session created with UUID-format session ID.

**Models returned:** 3 simple IDs:
- `default`
- `sonnet`
- `haiku`

Current model: `default`

**Finding:** Smallest model catalog of any agent probed. Model IDs are simple unversioned names — a fourth format after Gemini's flat versioned IDs, OpenCode's `provider/model` namespaced IDs, and Cursor's `model[params]` annotated IDs. The `default` model maps to Claude Opus 4.6 at runtime (confirmed by engine self-identification).

## Step 3: Execution Model — LOCAL with Full Permission Gating

**Action:** Sent `session/prompt` with the intro.sh exercise.

**Result:** Agent processed prompt locally. Two permission gates were encountered:

1. **File write** — `session/request_permission` with `kind=edit`: "Write intro.sh"
2. **Terminal execute** — `session/request_permission` with `kind=execute`: "chmod +x ... && ... /intro.sh"

**Client call stats:** 0 fs reads, 0 fs writes, 0 terminal creates, 2 permission requests.

**Finding:** Claude Code executes everything locally after permission is approved. Client `fs/write_text_file` and `terminal/create` methods are never called — the agent handles execution itself. This matches Cursor's model (local + permission gating) but differs from Gemini (delegated execution) and OpenCode (local, no gating).

## Step 4: Permission Option ID — "allow"

**Action:** Responded to both permission requests with `AllowedOutcome`.

**Result:** Both permissions approved successfully. Agent proceeded with file creation and terminal execution.

**Permission option ID:** `allow`

**Finding:** Third permission option ID observed across agents:
- Gemini: `proceed_once`
- Cursor: `allow-once`
- Claude Code: `allow`

The `allow` option (without `-once` suffix) suggests a broader grant semantic compared to the other agents. Permission option IDs cannot be hardcoded — must be read from the permission request options.

## Step 5: Full End-to-End Success

**Action:** Full probe completed end-to-end.

1. `initialize` — @zed-industries/claude-agent-acp v0.21.0, no auth methods
2. `session/new` — session created, 3 models available, current=default
3. `session/prompt` — agent processes prompt
4. `session/request_permission` (edit) — approved with `allow`
5. Agent writes file locally (no client fs call)
6. `session/request_permission` (execute) — approved with `allow`
7. Agent runs command locally (no client terminal call)
8. `session/update` stream — 32 updates with final output
9. `stopReason: end_turn`

**Result:**
```
Coding engine: Claude Opus 4.6
Today's Date: ...
```

intro.sh created on disk, executable, content correct.

**Observation:** Engine identifies itself as "Claude Opus 4.6" even though the model ID is `default`. The agent resolves the model alias internally and the underlying engine knows its true identity.

## Step 6: Session Update Volume

32 session updates observed for the intro.sh exercise. This places Claude Code between OpenCode (23) and Cursor (48) in streaming granularity.

## Comparison: Five Agents

| Dimension | Gemini CLI | OpenCode | Cursor Agent | Claude Code | Droid |
|---|---|---|---|---|---|
| Transport | stdio | stdio | stdio | stdio | stdio |
| Auth | required (oauth) | skippable | required (cursor_login) | none (env key) | required (device-pairing) |
| agentInfo | yes (name+version) | yes | no | yes (name+version) | yes (name+version) |
| Model format | flat versioned | provider/model | model[params] | simple unversioned | versioned |
| Model count | 7 | 80+ | many | 3 | 20 |
| Default model | auto-gemini-3 | opencode/big-pickle | default[] | default | glm-5 |
| Execution model | delegated | local | local + partial gating | local + full gating | delegated |
| Permission: file write | yes (gated) | no | no | yes (gated) | yes (gated) |
| Permission: terminal | yes (gated) | no | yes (gated) | yes (gated) | yes (gated) |
| Client fs calls | yes | no | no | no | no |
| Client terminal calls | yes | no | no | no | yes |
| Session updates (intro.sh) | 9 | 23 | 48 | 32 | N/A (hung) |
| Session ID format | UUID | ses_xxx | UUID | UUID | UUID |
| Permission option ID | proceed_once | (none) | allow-once | allow | proceed_once |
| intro.sh exercise | PASS | PASS | PASS | PASS | PASS (with fixes) |

## Key Takeaways

1. **Fourth execution model variant** — local execution with full permission gating (both file write and terminal). Cursor gates terminal only; Claude Code gates both. Neither delegates to the client like Gemini.
2. **No ACP auth needed** — Claude Code relies entirely on `ANTHROPIC_API_KEY` in the environment. Our credential sandboxing (`STRIPPED_ENV_KEYS` in process_manager) must ensure this key is injected when running Claude Code, unlike other agents where it should be stripped.
3. **Simple model IDs** — `default`, `sonnet`, `haiku` are the simplest model names seen. The adapter should not attempt to parse or normalize these — they work as-is.
4. **Permission option ID diversity confirmed** — `allow`, `allow-once`, `proceed_once`, and none. The adapter must read option IDs dynamically from each permission request.
5. **Zed wrapper, not native CLI** — The ACP-capable binary is `claude-agent-acp` from `@zed-industries`, not Anthropic's `claude` CLI. Agent identity metadata reflects the wrapper, while the engine identity reflects the underlying model.
