# OpenCode — ACP Integration Effort Log

Agent: OpenCode v1.2.26
Binary: `opencode acp`
Transport: stdio (not HTTP — `--port` flag NOT needed for ACP)
Date: 2026-03-14

## Step 1: Transport Discovery

**Hypothesis:** OpenCode needs `--port 0` for HTTP transport based on MDS spec.

**Action:** Ran `opencode acp --port 0 --print-logs` — got structured log output on stderr, no JSON-RPC on stdout.

**Action:** Ran `opencode acp` (no --port) via SDK's `spawn_agent_process` over stdio.

**Result:** Initialize succeeded immediately. Stdio transport works.

**Finding:** `opencode acp` without `--port` uses stdio, same as Gemini. The `--port` flag is for HTTP transport (separate concern). Our MDS spec assumed HTTP was required — it's not.

## Step 2: Initialize

**Result:**
- agentInfo: OpenCode v1.2.26
- loadSession: true
- image: true
- audio: false
- embeddedContext: true
- authMethods: `["opencode-login"]`

**Anomaly vs Gemini:** Only one auth method, generic ID `opencode-login` (vs Gemini's specific `oauth-personal`).

## Step 3: Auth

**Action:** Sent `authenticate(methodId="opencode-login")`.

**Result:** `Internal error` — auth method failed.

**Action:** Skipped auth, proceeded to session/new.

**Result:** Session created successfully without authentication.

**Finding:** OpenCode handles auth internally using stored credentials (`~/.local/share/opencode/auth.json`). The ACP `authenticate` method is either not fully implemented or not required. This is the opposite of Gemini where auth is mandatory.

## Step 4: Session — Dynamic Models

**Result:** Session created with ID `ses_...` format (differs from Gemini's UUID).

**Models returned:** 80+ models including:
- `google/gemini-3-pro-preview`, `google/gemini-3-flash-preview`, `google/gemini-2.5-*`
- `opencode/big-pickle` (custom model, the default)
- `opencode/gpt-5-nano`
- Free models: `opencode/nemotron-3-super-free`, `opencode/minimax-m2.5-free`, `opencode/mimo-v2-flash-free`
- Model variants with quality tiers: `/low`, `/medium`, `/high`, `/max`

**Current model:** `opencode/big-pickle`

**Finding:** OpenCode has far more models than Gemini, including its own and quality-tier variants. Model IDs use `provider/model` format (vs Gemini's flat IDs).

## Step 5: Prompt — Full Exercise

**Action:** Sent intro.sh prompt.

**Result:** Complete success on first attempt.

```
Coding engine: big-pickle
Today's date: Sat Mar 14 15:50:08 PDT 2026
```

File created on disk (74 bytes), executable, correct content.

**stopReason:** `end_turn`

## Step 6: Execution Model — LOCAL

**Client call stats:** 0 fs reads, 0 fs writes, 0 terminal creates, 0 permissions.

**Finding:** OpenCode executes everything locally. Zero delegation to client. Zero permission gates. Agent reads/writes files and runs commands directly on disk without asking. This is the opposite of Gemini's fully-delegated model.

## Step 7: No Permission Gating

**Finding:** OpenCode sent zero `session/request_permission` notifications. All tool executions happened silently — agent just did them and reported results via `session/update` stream.

This means for OpenCode:
- Our `request_permission` handler is never called
- Our `write_text_file` / `create_terminal` handlers are never called
- We observe results purely through `session/update` notifications

## Comparison: OpenCode vs Gemini

| Dimension | Gemini CLI | OpenCode |
|---|---|---|
| Transport | stdio | stdio (--port for HTTP optional) |
| Auth | required (oauth-personal) | not needed (internal) |
| Execution model | DELEGATED | LOCAL |
| Permission gating | yes (every write/execute) | none |
| Client fs calls | yes | no |
| Client terminal calls | yes | no |
| Models | 7 (flat IDs) | 80+ (provider/model format, quality tiers) |
| Default model | auto-gemini-3 | opencode/big-pickle |
| Session ID format | UUID | ses_xxx prefixed |
| Session updates | 9 for intro.sh | 23 for intro.sh |

## Key Takeaways

1. **Execution model is agent-specific** — confirmed. Cannot generalize from Gemini.
2. **Auth is optional** — some agents handle it internally. Must handle auth failure gracefully.
3. **Permission gating is optional** — some agents just execute without asking. Our permission handler must be ready to never be called.
4. **Model ID formats vary** — `gemini-3-flash-preview` vs `google/gemini-3-flash-preview`. Normalization needed at adapter level.
5. **Quality tiers** — OpenCode introduces `/low`, `/high`, `/max` model variants. New dimension not seen in Gemini.
