"""Core harness logic - uses actual MCP layer with mock API service."""

from pathlib import Path
from typing import Optional

from nautex.api.scope_context_model import TaskStatus
from nautex.models.config import NautexConfig, MCPOutputFormat
from nautex.models.mcp import format_response_as_markdown
from nautex.services.mcp_service import (
    MCPService,
    mcp_server_set_service_instance,
    mcp_handle_next_scope,
    mcp_handle_update_tasks,
)
from .mock_api_service import MockNautexAPIService
from .task_tree_state import TaskTreeStateService


class MockConfigService:
    """Minimal config service for testing."""

    def __init__(self):
        self.config = NautexConfig(
            project_id="test-project",
            plan_id="test-plan",
            response_format=MCPOutputFormat.MD_YAML
        )
        self.cwd = Path.cwd()


class TestMCPService(MCPService):
    """MCPService subclass that skips document loading."""

    async def ensure_dependency_documents_on_disk(self):
        return {}  # No docs in test mode

    def is_configured(self) -> bool:
        return True  # Always configured for tests


class InteractiveHarness:
    """Harness that uses actual MCP layer with mock API service."""

    def __init__(self, use_mock: bool = True):
        """Initialize the harness.

        Args:
            use_mock: If True, use MockNautexAPIService. If False, expects
                     MCP service to be configured externally.
        """
        self._mock_api: Optional[MockNautexAPIService] = None
        self.task_tree = TaskTreeStateService()  # Mode-agnostic tree state

        if use_mock:
            self._setup_mock_mcp()

    def _setup_mock_mcp(self):
        """Set up MCP service with mock API."""
        self._mock_api = MockNautexAPIService()

        mcp_service = TestMCPService(
            config_service=MockConfigService(),
            nautex_api_service=self._mock_api,
            integration_status_service=None,
            document_service=None
        )
        mcp_server_set_service_instance(mcp_service)

        # Initialize tree from mock data
        self._sync_tree_from_mock()

    def _sync_tree_from_mock(self):
        """Sync tree state from mock API (mock mode only)."""
        if self._mock_api:
            mock_data = self._mock_api.get_tasks_as_scope_data()
            self.task_tree.update_from_scope_data(mock_data)

    @property
    def mock_api(self) -> Optional[MockNautexAPIService]:
        """Access to mock API for TUI task display."""
        return self._mock_api

    async def cmd_next(self, full: bool = False) -> str:
        """Execute next_scope command via actual MCP layer.

        Args:
            full: Whether to request full mode

        Returns:
            Rendered output string (markdown with YAML)
        """
        result = await mcp_handle_next_scope(full=full)
        data = result.get("data", {})

        # Update tree from response (works for both mock and API)
        if "tasks" in data:
            self.task_tree.update_from_scope_data(data["tasks"])

        if result.get("success"):
            return format_response_as_markdown("Next Scope", data)
        else:
            return format_response_as_markdown("Error", result)

    async def cmd_update(self, designator: str, status: TaskStatus) -> str:
        """Update a task's status via actual MCP layer.

        Args:
            designator: Task designator
            status: New status

        Returns:
            Rendered response string
        """
        ops = [{"task_designator": designator, "updated_status": status.value}]
        result = await mcp_handle_update_tasks(ops)
        return format_response_as_markdown(
            "Update Result",
            result.model_dump(exclude_none=True)
        )

    async def cmd_batch_update(self, updates: list) -> str:
        """Update multiple tasks via actual MCP layer.

        Args:
            updates: List of (designator, status) tuples

        Returns:
            Rendered response string
        """
        ops = [
            {"task_designator": d, "updated_status": s.value}
            for d, s in updates
        ]

        # Optimistic update - apply locally before API call
        self.task_tree.apply_status_updates(updates)

        result = await mcp_handle_update_tasks(ops)

        # Update from scope in response (clears optimistic, gets new focus)
        if result.next_scope and "tasks" in result.next_scope:
            self.task_tree.update_from_scope_data(result.next_scope["tasks"])
        # In mock mode: optimistic stays until user fetches scope (n/f)

        return format_response_as_markdown(
            "Update Result",
            result.model_dump(exclude_none=True)
        )

    def cmd_reset(self) -> str:
        """Reset mock API to initial state.

        Returns:
            Status message
        """
        if self._mock_api:
            self._mock_api.reset()
            self._sync_tree_from_mock()  # Re-sync tree after reset
            return "Reset to initial state"
        self.task_tree.reset()
        return "Tree state reset (no mock API)"
