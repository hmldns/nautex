"""Unit tests for the full flag feature in next_scope command."""

import pytest

from src.nautex.api.scope_context_model import (
    ScopeContext,
    ScopeTask,
    ScopeContextMode,
    TaskStatus,
    TaskType,
)
from src.nautex.models.mcp import (
    ScopeRenderMode,
    MCPScopeResponse,
    MCPScopeTask,
    MCPWorkflowInfo,
    convert_scope_context_to_mcp_response,
)


# ============================================================================
# ScopeRenderMode Tests
# ============================================================================

class TestScopeRenderMode:
    """Tests for ScopeRenderMode enum."""

    def test_render_modes_exist(self):
        """Test that render modes are defined."""
        assert ScopeRenderMode.FULL == "full"
        assert ScopeRenderMode.COMPACT == "compact"


# ============================================================================
# Compact Rendering Tests
# ============================================================================

class TestCompactRendering:
    """Tests for compact response rendering."""

    def _create_test_response(self) -> MCPScopeResponse:
        """Create a test MCPScopeResponse with nested tasks."""
        subtask1 = MCPScopeTask(
            designator="T-1.1",
            name="Subtask 1",
            description="Description 1",
            status=TaskStatus.DONE,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            requirements=["REQ-1"],
            files=["file1.py"],
        )
        subtask2 = MCPScopeTask(
            designator="T-1.2",
            name="Subtask 2",
            description="Description 2",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=True),
            requirements=["REQ-2"],
            files=["file2.py"],
        )
        parent = MCPScopeTask(
            designator="T-1",
            name="Parent Task",
            description="Parent description",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            subtasks=[subtask1, subtask2],
        )
        # A completely separate task not in focus branch
        other_task = MCPScopeTask(
            designator="T-2",
            name="Other Task",
            description="Other description",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
        )

        return MCPScopeResponse(
            progress_context="Test context",
            instructions="Test instructions",
            documents_paths={"PRD": "docs/prd.md"},
            tasks=[parent, other_task],
        )

    def test_full_mode_includes_all_tasks(self):
        """Test that full mode includes all tasks with full details."""
        response = self._create_test_response()

        result = response.render_response(ScopeRenderMode.FULL)

        # Check that both top-level tasks are present
        tasks = result["tasks"]
        assert len(tasks) == 2
        assert tasks[0]["designator"] == "T-1"
        assert tasks[1]["designator"] == "T-2"

        # Check that all details are present
        assert "description" in tasks[0]
        assert "description" in tasks[1]
        assert "subtasks" in tasks[0]
        assert "progress_context" in result
        assert "documents_paths" in result

    def test_compact_mode_returns_only_focus_tasks(self):
        """Test that compact mode returns only focus tasks directly."""
        response = self._create_test_response()

        result = response.render_response(ScopeRenderMode.COMPACT)

        # Only focus task T-1.2 should be present
        tasks = result["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["designator"] == "T-1.2"

    def test_compact_mode_focus_tasks_have_full_details(self):
        """Test that focus tasks have full details in compact mode."""
        response = self._create_test_response()

        result = response.render_response(ScopeRenderMode.COMPACT)

        focus_task = result["tasks"][0]
        assert focus_task["designator"] == "T-1.2"
        assert focus_task["description"] == "Description 2"
        assert "REQ-2" in focus_task["requirements"]
        assert "file2.py" in focus_task["files"]

    def test_compact_mode_excludes_context_fields(self):
        """Test that compact mode excludes progress_context, instructions, documents_paths."""
        response = self._create_test_response()

        result = response.render_response(ScopeRenderMode.COMPACT)

        assert "progress_context" not in result
        assert "instructions" not in result
        assert "documents_paths" not in result

    def test_compact_mode_only_has_tasks_key(self):
        """Test that compact mode response only contains tasks key."""
        response = self._create_test_response()

        result = response.render_response(ScopeRenderMode.COMPACT)

        assert list(result.keys()) == ["tasks"]

    def test_default_renders_full(self):
        """Test that no mode defaults to full mode."""
        response = self._create_test_response()

        result = response.render_response()

        # Should include all tasks (default is FULL)
        tasks = result["tasks"]
        assert len(tasks) == 2
        assert "progress_context" in result


# ============================================================================
# Focus Task Collection Tests
# ============================================================================

class TestFocusTaskCollection:
    """Tests for focus task collection logic."""

    def test_deeply_nested_focus_collected(self):
        """Test that deeply nested focus tasks are collected."""
        deep_focus = MCPScopeTask(
            designator="T-1.1.1",
            name="Deep Focus",
            description="Deep description",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=True),
        )
        middle = MCPScopeTask(
            designator="T-1.1",
            name="Middle",
            description="Middle description",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            subtasks=[deep_focus],
        )
        parent = MCPScopeTask(
            designator="T-1",
            name="Parent",
            description="Parent description",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            subtasks=[middle],
        )

        response = MCPScopeResponse(
            progress_context="Test",
            instructions="Test",
            documents_paths={},
            tasks=[parent],
        )

        result = response.render_response(ScopeRenderMode.COMPACT)

        # Only the deeply nested focus task should be returned
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["designator"] == "T-1.1.1"

    def test_multiple_focus_tasks_collected(self):
        """Test that multiple focus tasks from different branches are collected."""
        focus1 = MCPScopeTask(
            designator="T-1.1",
            name="Focus 1",
            description="Description 1",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=True),
        )
        focus2 = MCPScopeTask(
            designator="T-2.1",
            name="Focus 2",
            description="Description 2",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=True),
        )
        parent1 = MCPScopeTask(
            designator="T-1",
            name="Parent 1",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            subtasks=[focus1],
        )
        parent2 = MCPScopeTask(
            designator="T-2",
            name="Parent 2",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
            subtasks=[focus2],
        )

        response = MCPScopeResponse(
            progress_context="Test",
            instructions="Test",
            documents_paths={},
            tasks=[parent1, parent2],
        )

        result = response.render_response(ScopeRenderMode.COMPACT)

        # Both focus tasks should be collected
        assert len(result["tasks"]) == 2
        designators = [t["designator"] for t in result["tasks"]]
        assert "T-1.1" in designators
        assert "T-2.1" in designators

    def test_no_focus_tasks_returns_empty(self):
        """Test that compact mode with no focus tasks returns empty task list."""
        task = MCPScopeTask(
            designator="T-1",
            name="No Focus",
            description="Description",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            workflow_info=MCPWorkflowInfo(in_focus=False),
        )

        response = MCPScopeResponse(
            progress_context="Test",
            instructions="Test",
            documents_paths={},
            tasks=[task],
        )

        result = response.render_response(ScopeRenderMode.COMPACT)

        # No focus tasks means empty task list
        assert len(result["tasks"]) == 0


# ============================================================================
# Mock Provider Tests
# ============================================================================

class TestMockProvider:
    """Tests for the mock scope provider."""

    @pytest.mark.asyncio
    async def test_initial_state(self):
        """Test mock provider initial state."""
        from tools.scope_harness.mock_scope_provider import MockScopeProvider

        provider = MockScopeProvider()
        scope = await provider.get_scope(None, None)

        assert len(scope.tasks) == 2
        assert len(scope.focus_tasks) > 0

    @pytest.mark.asyncio
    async def test_update_task_status(self):
        """Test updating task status."""
        from tools.scope_harness.mock_scope_provider import MockScopeProvider
        from tools.scope_harness.scope_provider import TaskOperation

        provider = MockScopeProvider()

        # Get initial scope
        scope = await provider.get_scope(None, None)
        focus_task = scope.focus_tasks[0]

        # Update to done
        await provider.update_tasks([
            TaskOperation(focus_task, TaskStatus.DONE)
        ])

        # Focus should have changed
        new_scope = await provider.get_scope(None, None)
        assert focus_task not in new_scope.focus_tasks or \
               new_scope.find_task_by_designator(focus_task).status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_reset(self):
        """Test reset functionality."""
        from tools.scope_harness.mock_scope_provider import MockScopeProvider
        from tools.scope_harness.scope_provider import TaskOperation

        provider = MockScopeProvider()

        # Make some changes
        scope = await provider.get_scope(None, None)
        await provider.update_tasks([
            TaskOperation(scope.focus_tasks[0], TaskStatus.DONE)
        ])

        # Reset
        provider.reset()

        # Should be back to initial state
        new_scope = await provider.get_scope(None, None)
        assert len(new_scope.tasks) == 2


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for the full feature."""

    @pytest.mark.asyncio
    async def test_full_flow_with_harness(self):
        """Test complete flow using the interactive harness."""
        from tools.scope_harness import MockScopeProvider, ScopeRenderer, InteractiveHarness

        provider = MockScopeProvider()
        renderer = ScopeRenderer()
        harness = InteractiveHarness(provider, renderer)

        # Request compact mode
        output = await harness.cmd_next(full=False)
        assert "Next Scope" in output

        # Request full mode
        output = await harness.cmd_next(full=True)
        assert "Next Scope" in output

    @pytest.mark.asyncio
    async def test_compact_vs_full_output_differs(self):
        """Test that compact and full modes produce different output."""
        from tools.scope_harness import MockScopeProvider, ScopeRenderer, InteractiveHarness

        provider = MockScopeProvider()
        renderer = ScopeRenderer()
        harness = InteractiveHarness(provider, renderer)

        compact_output = await harness.cmd_next(full=False)
        full_output = await harness.cmd_next(full=True)

        # Full mode should have more content (includes context, docs, ancestors)
        assert len(full_output) > len(compact_output)

    @pytest.mark.asyncio
    async def test_stateless_behavior(self):
        """Test that repeated calls produce consistent results (stateless)."""
        from tools.scope_harness import MockScopeProvider, ScopeRenderer, InteractiveHarness

        provider = MockScopeProvider()
        renderer = ScopeRenderer()
        harness = InteractiveHarness(provider, renderer)

        # Multiple compact calls should produce same output (stateless)
        output1 = await harness.cmd_next(full=False)
        output2 = await harness.cmd_next(full=False)

        assert output1 == output2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
