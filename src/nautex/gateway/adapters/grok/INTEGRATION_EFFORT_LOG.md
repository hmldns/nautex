# Grok Build — Integration Effort Log

Agent: `grok_build`  
Binary: `grok` (native, no npm ACP bridge)  
Versions probed: `0.2.111` (2026-07-22)

## Launch

```
grok agent -m grok-4.5 --reasoning-effort high stdio
```

Flags belong on `agent`, before the `stdio` subcommand. Wrong order
(`grok agent stdio -m …`) does not apply model/effort.

## Initialize

| Field | Observed |
|---|---|
| protocolVersion | 1 |
| agentInfo | **null** (same as Cursor/Goose) |
| loadSession | true |
| image | false |
| embeddedContext | true |
| authMethods | `cached_token`, `grok.com` |
| field_meta.modelState | models + reasoning efforts |
| field_meta.agentVersion | 0.2.111 |

## Auth

- `authenticate(cached_token)` succeeds when `~/.grok/auth.json` present.
- Prefer `cached_token` over `grok.com` (browser OAuth).
- Headless: inject `XAI_API_KEY` via session credentials (stripped from host env).

## Session

- `session/new` → UUID session id
- `config_options` → **null** (models live under `field_meta["x.ai/sessionConfig"]`)
- Default without flags: model `grok-4.5`, mode `high`

## Model / effort selection

| Mechanism | Works? |
|---|---|
| CLI `-m` / `--reasoning-effort` at launch | **yes** |
| `session/set_config_option` | **no** (Method not found) |
| `session/set_mode` (high/medium/low) | **yes** |
| Mid-session model id switch | **no** — requires respawn |

Adapter strategy:

1. Launch with `-m <model>` (default `grok-4.5`) and `--reasoning-effort high`
2. After session/new, call `set_session_mode("high")` again
3. Parse models from field_meta into `available_models` (shared extractor)
4. `set_model`: effort ids → `set_session_mode`; same model id → re-assert high; other models → fail (need respawn)

## Prompt

- Short text prompt → `stop_reason: end_turn`
- Usage/tokens in prompt response `field_meta`

## Permissions / execution model

**Fully delegated** (like Gemini / Droid):

- `fs/read_text_file` + `fs/write_text_file` → client
- `terminal/create` → client (often full shell line as `command`, empty `args`)

Production intro.sh exercise (2026-07-22): **PASS** via `GrokAdapter`
(`create_adapter("grok_build")` → write + chmod + run, `stop_reason=end_turn`).
No `session/request_permission` observed on the happy path (auto path).

Gateway client notes:

- ACP write body field is `content` (not `text`) — fixed in `acp_client.py`
- Terminal: shell when `args` empty; exec when argv split is provided

## SDK compatibility

`agent-client-protocol` Python SDK `spawn_agent_process` works cleanly.
