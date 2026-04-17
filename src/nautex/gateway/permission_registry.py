"""Permission registry — solid-state tracking of asyncio.Future permission gates.

When an agent requests a sensitive operation (file write, terminal exec),
the adapter calls register_request() which blocks on a Future until resolved.

Three resolution paths based on config:
1. auto_approve: Future resolved immediately (no human in the loop)
2. headless_mode: Permission delegated to cloud frontend via WS uplink
3. Interactive: Notification pushed to local TUI via event bus

On connection drop, reject_all() cancels all hanging futures to prevent
indefinite agent stalls.

Reference: MDSNAUTX-14, MDSNAUTX-17
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, Optional

from .event_bus import GatewayEventBus, LocalEventKind
from .models import PermissionRequestPayload, PermissionResponsePayload

logger = logging.getLogger(__name__)


class PermissionRegistry:
    """Solid storage for permission states existing in space and time.

    The registry owns the asyncio.Future lifecycle. The event bus is used
    only for transient notifications — actual state lives here.
    """

    def __init__(
        self,
        event_bus: GatewayEventBus,
        auto_approve: bool = False,
        headless_mode: bool = False,
        on_delegate_to_cloud: Optional[Callable[[PermissionRequestPayload], None]] = None,
    ):
        self._event_bus = event_bus
        self._auto_approve = auto_approve
        self._headless_mode = headless_mode
        self._on_delegate_to_cloud = on_delegate_to_cloud

        self._pending: Dict[str, PermissionRequestPayload] = {}
        self._futures: Dict[str, asyncio.Future[PermissionResponsePayload]] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def is_pending(self, permission_id: str) -> bool:
        return permission_id in self._pending

    async def register_request(
        self, payload: PermissionRequestPayload
    ) -> PermissionResponsePayload:
        """Register a permission request and block until resolved.

        The caller (adapter) awaits this — execution is suspended until
        the future is resolved by one of the four paths:
        1. payload.policy_action set → resolve immediately with that action,
           still notify the cloud for history persistence.
        2. auto_approve → resolve immediately with approve.
        3. headless_mode → delegate to cloud, wait for WS response.
        4. interactive → notify local TUI, wait for user.
        """
        future: asyncio.Future[PermissionResponsePayload] = asyncio.get_event_loop().create_future()
        self._futures[payload.permission_id] = future
        self._pending[payload.permission_id] = payload

        logger.debug("Permission registered: %s (%s)", payload.permission_id, payload.tool_name)

        if payload.policy_action is not None:
            # Record in cloud history first (item created in terminal state)
            if self._headless_mode and self._on_delegate_to_cloud:
                self._on_delegate_to_cloud(payload)
            self.resolve_request(payload.permission_id, payload.policy_action.value)
        elif self._auto_approve:
            self.resolve_request(payload.permission_id, "approve")
        elif self._headless_mode:
            if self._on_delegate_to_cloud:
                self._on_delegate_to_cloud(payload)
            # Future stays pending — will be resolved when WS response arrives
        else:
            # Notify local TUI
            await self._event_bus.publish(LocalEventKind.PERMISSION_REQUEST, payload)

        return await future

    def resolve_request(self, permission_id: str, action: str) -> None:
        """Resolve a pending permission request (approve or deny).

        Called by: TUI (interactive), WS handler (headless), or auto_approve.
        """
        future = self._futures.pop(permission_id, None)
        request = self._pending.pop(permission_id, None)

        if future and not future.done():
            response = PermissionResponsePayload(
                permission_id=permission_id,
                acp_session_id=request.acp_session_id if request else "",
                action=action,
            )
            future.set_result(response)
            logger.debug("Permission resolved: %s → %s", permission_id, action)

    def reject_all(self, reason: str = "connection_lost") -> int:
        """Reject all pending permissions. Returns count rejected.

        Called on WS disconnect or daemon shutdown to unblock stalled adapters.
        """
        count = 0
        for pid in list(self._futures.keys()):
            future = self._futures.pop(pid, None)
            self._pending.pop(pid, None)
            if future and not future.done():
                future.set_result(PermissionResponsePayload(
                    permission_id=pid,
                    action="deny",
                ))
                count += 1
        logger.info("Rejected %d pending permissions: %s", count, reason)
        return count
