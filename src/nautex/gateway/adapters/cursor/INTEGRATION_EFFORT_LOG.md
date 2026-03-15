# Cursor Agent — ACP Integration Effort Log

Agent: Cursor Agent (Auto router)
Binary: `cursor-agent acp`
Transport: stdio
Date: 2026-03-14

## Step 1: Initial Probe — Paywall

**Action:** Ran probe with default model (none specified).

**Result:** Auth succeeded (`cursor_login`), session created, but prompt returned: "Upgrade your plan to continue." stopReason: `end_turn`.

**Finding:** Cursor requires model selection. Without it, defaults to a paid tier. User reported `model=auto` works on free plan.

## Step 2: Model=auto — Full Success

**Action:** Set `DEFAULT_MODEL = "auto"` in probe. `set_session_model("auto")` fails with "Invalid params" but the default model is already `default[]` which maps to auto routing.

**Result:** Full intro.sh exercise completed.

```
Coding engine: Auto
Today's date: Sat Mar 14 04:42:57 PM PDT 2026
```

## Step 3: Observations

### No agentInfo
Initialize response does NOT include `agentInfo` (no name, no version). Unlike Gemini and OpenCode which both report.

### Model Format — Unique
Model IDs include inline capability annotations:
- `claude-sonnet-4-6[thinking=true,context=200k,effort=medium]`
- `gpt-5.3-codex[reasoning=medium,fast=false]`
- `gemini-3.1-pro[]`
- `claude-opus-4-6[thinking=true,context=200k,effort=high,fast=false]`

This is a third format: Gemini uses flat IDs, OpenCode uses `provider/model`, Cursor uses `model[params]`.

### Execution Model — LOCAL with Partial Permission Gating
- **File write**: happened silently, no permission gate, no client fs calls
- **Terminal execute** (`chmod +x && ./intro.sh`): triggered `session/request_permission` with `kind=execute`
- **Client calls**: 0 fs reads, 0 fs writes, 0 terminal creates, 1 permission request

This is a **hybrid** model:
- File ops: local, no gating (like OpenCode)
- Terminal ops: local execution but gated by permission request (partially like Gemini)
- Client never asked to execute anything — agent does it all locally after permission

### Session Updates Volume
48 session updates for intro.sh — highest observed. Very granular token-level thought streaming.

### Permission Option IDs
- `allow-once` (not `proceed_once` like Gemini)
- Permission `kind=execute` for terminal commands

## Comparison: Three Agents

| Dimension | Gemini CLI | OpenCode | Cursor Agent |
|---|---|---|---|
| Transport | stdio | stdio | stdio |
| Auth | required (oauth) | skippable | required (cursor_login) |
| agentInfo | yes (name+version) | yes | no |
| Model format | flat | provider/model | model[params] |
| Default model | auto-gemini-3 | opencode/big-pickle | default[] |
| Execution model | delegated | local | local + partial gating |
| Permission: file write | yes (gated) | no | no |
| Permission: terminal | yes (gated) | no | yes (gated) |
| Client fs calls | yes | no | no |
| Client terminal calls | yes | no | no |
| Session updates (intro.sh) | 9 | 23 | 48 |
| Session ID format | UUID | ses_xxx | UUID |
| Permission option ID | proceed_once | (none) | allow-once |

## Key Takeaways

1. **Third execution model discovered** — local execution with selective permission gating. Neither fully delegated nor fully local.
2. **Model format diversity grows** — three formats now. Normalization layer needed.
3. **Permission option IDs vary** — `proceed_once` vs `allow-once`. Cannot hardcode.
4. **No agentInfo is valid** — adapter must handle missing agent metadata.
5. **Paywall gotcha** — model selection required or agent refuses to work. Default model may not be the free one.
