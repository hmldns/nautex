"""Grok Build adapter — native ACP via `grok agent stdio`.

Quirks (observed on grok 0.2.111):
- Launch: `grok agent -m <model> --reasoning-effort <level> stdio`
  (flags belong on `agent`, before the `stdio` subcommand).
- Models are advertised under field_meta (`x.ai/sessionConfig`,
  `modelState`), not standard ACP `config_options`. Shared extractor
  in gateway.config handles this.
- `session/set_config_option` is **not** implemented (Method not found).
- Reasoning effort is switched via `session/set_mode` (high|medium|low).
- Default without flags is already grok-4.5 + high; we still force both
  at launch and re-assert high effort after session/new.

Reference: adapters/grok/INTEGRATION_EFFORT_LOG.md
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...config import extract_session_effort
from ...models import AgentSessionConfig
from ..acp_adapter import ACPAgentAdapter
from ..launch_config import LaunchAdjustment

logger = logging.getLogger(__name__)

# Defaults — user requirement: Grok 4.5 at maximum effort.
DEFAULT_MODEL = "grok-4.5"
MAX_EFFORT = "high"
EFFORT_IDS = frozenset({"high", "medium", "low"})


class GrokAdapter(ACPAgentAdapter):
    """ACP adapter specialized for the Grok Build CLI."""

    def __init__(self, agent_id: str, directory_scope: str):
        super().__init__(agent_id, directory_scope)
        self._current_effort: str = MAX_EFFORT
        self._launch_model: str = DEFAULT_MODEL

    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        """Build `agent -m <model> --reasoning-effort high stdio` argv tail.

        Registration launch_args is just `["agent"]`; we append model/effort
        flags and the `stdio` subcommand here so order is correct.
        """
        model = (config.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        # Allow encoding effort in model string as "grok-4.5:high" if UI ever
        # surfaces combined ids; otherwise always max effort.
        effort = MAX_EFFORT
        if ":" in model:
            base, maybe_effort = model.rsplit(":", 1)
            if maybe_effort in EFFORT_IDS:
                model, effort = base, maybe_effort
        if model in EFFORT_IDS:
            # Settings UI accidentally sent an effort id as "model"
            effort = model
            model = DEFAULT_MODEL

        self._launch_model = model
        self._current_effort = effort
        extra = [
            "-m", model,
            "--reasoning-effort", effort,
            "stdio",
        ]
        logger.info(
            "Grok launch: model=%s effort=%s args=%s",
            model, effort, extra,
        )
        return LaunchAdjustment(extra_args=extra)

    async def _after_session_created(self, session: Any) -> None:
        """Force max reasoning effort and refresh model state from field_meta."""
        if session is not None:
            self._apply_model_state(session)
            effort = extract_session_effort(session)
            if effort:
                self._current_effort = effort

        # Always re-assert high effort after create/load (user requirement).
        await self._ensure_effort(MAX_EFFORT)

        # Prefer launch model when session meta is empty.
        if not self._current_model:
            self._current_model = self._launch_model
        if not self._available_models:
            self._available_models = [self._launch_model]

        logger.info(
            "Grok session ready: model=%s effort=%s models=%s",
            self._current_model, self._current_effort, self._available_models,
        )

    async def _ensure_effort(self, effort: str) -> bool:
        """Apply reasoning effort via session/set_mode. Returns True on success."""
        if effort not in EFFORT_IDS:
            logger.warning("Unknown Grok effort %r — expected one of %s", effort, sorted(EFFORT_IDS))
            return False
        try:
            conn, acp_sid = self._require_session("set_effort")
            await conn.set_session_mode(session_id=acp_sid, mode_id=effort)
            self._current_effort = effort
            logger.info("Grok effort set to %s (session=%s)", effort, acp_sid)
            return True
        except Exception as e:
            logger.warning("Grok set_session_mode(%s) failed: %s", effort, e)
            return False

    async def set_model(self, model_id: str) -> bool:
        """Harmonize settings UI model changes onto Grok's APIs.

        - Effort ids (high/medium/low) → session/set_mode
        - Model ids matching current launch model → ensure max effort, success
        - Other model ids → not supported mid-session (no set_config_option);
          return False so backend does not claim a switch that did not happen.

        Mid-session model changes require respawning with a new `-m` flag.
        """
        mid = (model_id or "").strip()
        if not mid:
            return False

        if mid in EFFORT_IDS:
            return await self._ensure_effort(mid)

        # Combined "model:effort"
        if ":" in mid:
            base, maybe_effort = mid.rsplit(":", 1)
            if maybe_effort in EFFORT_IDS:
                ok_effort = await self._ensure_effort(maybe_effort)
                if base == self._current_model or base == self._launch_model:
                    self._current_model = base
                    return ok_effort
                logger.warning(
                    "Grok mid-session model switch to %s unsupported; "
                    "effort=%s applied=%s (relaunch required for model)",
                    base, maybe_effort, ok_effort,
                )
                return False

        if mid == self._current_model or mid == self._launch_model:
            self._current_model = mid
            # User asked for max effort whenever we touch model selection
            await self._ensure_effort(MAX_EFFORT)
            return True

        if mid in self._available_models:
            logger.warning(
                "Grok does not implement session/set_config_option; "
                "cannot switch model to %s mid-session (current=%s). "
                "Respawn with -m required.",
                mid, self._current_model,
            )
            return False

        logger.warning("Unknown Grok model id %r (available=%s)", mid, self._available_models)
        return False
