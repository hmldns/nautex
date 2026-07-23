"""Grok Build — static configuration notes.

Native ACP binary: `grok agent [options] stdio`.
No npm ACP bridge required (unlike claude-agent-acp / codex-acp).

Auth: ACP `cached_token` (~/.grok/auth.json) or `grok.com` OAuth;
headless machines may inject `XAI_API_KEY` via session credentials.
"""
