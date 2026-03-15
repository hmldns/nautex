# Gemini CLI — ACP Integration Effort Log

Agent: Gemini CLI v0.33.1
Binary: `gemini --acp`
Transport: stdio JSON-RPC
Date: 2026-03-14

## Step 1: Initial Probe (raw JSON-RPC, no SDK)

**Action:** Spawned `gemini --experimental-acp` via process_manager, sent hand-crafted JSON-RPC `initialize` with `protocolVersion: "2024-11-05"` (string).

**Result:** Agent rejected — `protocolVersion` must be an integer, not a string.

**Fix:** Changed to `protocolVersion: 1`.

**Finding:** ACP spec uses integer protocol versions, not date strings.

## Step 2: Initialize Success, Wrong Method Names

**Action:** Sent `session/create` and `prompt/execute`.

**Result:** Both returned `"Method not found"`. Initialize succeeded and returned agent info + auth methods.

**Fix:** After web research on official ACP spec:
- `session/create` → `session/new` (requires `cwd` and `mcpServers` params)
- `prompt/execute` → `session/prompt` (requires `prompt` as ContentBlock array, not `content`)

**Finding:** ACP method names differ from what MDS spec assumed. Correct methods: `initialize`, `authenticate`, `session/new`, `session/prompt`, `session/update`, `session/cancel`.

## Step 3: Auth Flow Discovery

**Action:** Agent returned `authMethods` array in initialize response. Sent `authenticate` with `methodId: "oauth-personal"`.

**Result:** Empty result `{}` = success. Agent used cached Google OAuth credentials from prior `gemini auth login`.

**Finding:** Agents are pre-authenticated on host. ACP `authenticate` simply activates existing credentials. No interactive auth needed.

## Step 4: Session Creates, Returns Dynamic Models

**Action:** Sent `session/new` with `cwd` and empty `mcpServers`.

**Result:** Got sessionId + unexpected bonus: `models.availableModels` array with 7 models and `models.currentModelId`.

**Models discovered:**
- `auto-gemini-3` (default)
- `auto-gemini-2.5`
- `gemini-3.1-pro-preview`
- `gemini-3-flash-preview`
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

**Finding:** Models come dynamically from session creation, not static manifests. `set_session_model()` switches model mid-session. Gemini 3.1 pro often 429s (capacity exhausted) — use flash for probing.

## Step 5: Delegation Model Discovery

**Action:** Sent `session/prompt` with empty `clientCapabilities: {}`. Agent started processing but sent `fs/read_text_file` request back to us.

**Result:** Stream hung — agent waiting for our filesystem response.

**Hypothesis:** Maybe if we don't declare capabilities, agent handles fs locally.

**Action:** Removed fs/terminal capabilities, retried.

**Result:** Agent still sent `session/request_permission` for file writes and terminal commands, then hung waiting for our response.

**Finding:** In ACP mode, Gemini CLI always delegates fs/terminal to the client. It does NOT execute locally. The agent is intentionally sandboxed — client IS the executor. This is fundamental to ACP architecture.

## Step 6: Permission Response Format (THE BLOCKER)

**Action:** Responded to `session/request_permission` with `RequestPermissionResponse(optionId="proceed_once")`.

**Result:** Agent received our approval but then retried the same operation repeatedly, getting `[object Object]` errors. File writes never landed on disk. Terminal commands never executed. Our `write_text_file` and `create_terminal` methods were never called.

**Root cause investigation:** Checked SDK schema — `RequestPermissionResponse` doesn't take `optionId`. It requires:
```python
RequestPermissionResponse(
    outcome=AllowedOutcome(option_id="proceed_once", outcome="selected")
)
```

The `outcome` field with a discriminated union (`AllowedOutcome` vs `DeniedOutcome`) was required. Our malformed response was silently rejected by the agent.

**Fix:** Used correct `AllowedOutcome` with `outcome="selected"`.

**Finding:** This was the single blocker preventing the entire flow from completing. The SDK's Pydantic models enforce the correct structure — always check `model_fields` for required fields and aliases.

## Step 7: Full End-to-End Success

**Action:** With fixed permission responses, full probe completed:

1. `initialize` → Gemini CLI v0.33.1, loadSession=true, image=true, audio=true
2. `authenticate` → oauth-personal, cached creds
3. `session/new` → session created, model switched to gemini-3-flash-preview
4. `session/prompt` → agent processes prompt
5. Agent sends `fs/read_text_file` → we return content (or empty for new files)
6. Agent sends `session/request_permission` (edit) → we approve with AllowedOutcome
7. Agent sends `fs/write_text_file` → we write to disk, return WriteTextFileResponse
8. Agent sends `session/request_permission` (execute) → we approve
9. Agent sends `terminal/create` → we spawn subprocess
10. Agent sends `terminal/output` → we return stdout
11. Agent sends `terminal/wait_for_exit` → we return exit code
12. Agent streams `session/update` with final message including terminal output
13. `stopReason: end_turn` — prompt complete

**Result:**
```
Coding Engine: Gemini CLI
Today's Date: Sat Mar 14 15:21:11 PDT 2026
```

intro.sh created on disk (74 bytes), executable, content correct.

## Capability Corrections (from probe vs spec)

| Capability | MDS Spec | Probe Reality |
|---|---|---|
| version | 0.32.0 | 0.33.1 |
| loadSession | false | true |
| audio | false | true |
| ACP flag | --experimental-acp | --acp (deprecated renamed) |
| Models | static list | dynamic from session/new |

## Key Takeaways for Adapter Implementation

1. **Gemini uses delegated execution** — in ACP mode, Gemini CLI delegates all fs/terminal ops to the client. Other agents may execute locally and just report results. This is agent-specific, not a protocol guarantee.
2. **Permission response format is critical** — must use `AllowedOutcome(outcome="selected")`, not bare `optionId`.
3. **Models are dynamic** — discovered at session creation, not hardcoded in adapter manifests.
4. **Auth is pass-through** — just activate pre-configured credentials via `authenticate` method.
5. **SDK handles framing** — use `agent-client-protocol` Python SDK, don't hand-roll JSON-RPC.
6. **Always check `model_fields`** — SDK Pydantic models have aliases and required fields that differ from what you'd guess.
