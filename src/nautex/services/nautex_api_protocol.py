"""Protocol for Nautex API services - enables clean mocking."""

from typing import Protocol, Optional, List

from ..api.scope_context_model import ScopeContext
from ..api.api_models import APIResponse, TaskOperation


class NautexAPIProtocol(Protocol):
    """Protocol for Nautex API services.

    Defines the interface for API services that can be used by MCPService.
    Both NautexAPIService (real) and MockNautexAPIService (test) implement this.
    """

    async def next_scope(
        self, project_id: str, plan_id: str, from_mcp: bool = False
    ) -> Optional[ScopeContext]:
        """Get next scope for the project/plan.

        Args:
            project_id: The project ID
            plan_id: The plan ID
            from_mcp: Whether the request is from MCP

        Returns:
            ScopeContext or None if no scope available
        """
        ...

    async def update_tasks(
        self, project_id: str, plan_id: str,
        operations: List[TaskOperation], from_mcp: bool = False
    ) -> APIResponse:
        """Update tasks in batch.

        Args:
            project_id: The project ID
            plan_id: The plan ID
            operations: List of task operations
            from_mcp: Whether the request is from MCP

        Returns:
            APIResponse with result
        """
        ...
