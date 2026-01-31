"""Unit tests for scope rendering rules."""

import pytest

from nautex.api.scope_context_model import TaskStatus, TaskType
from nautex.models.mcp import MCPScopeResponse, MCPScopeTask, MCPWorkflowInfo, ScopeRenderMode
from nautex.models.scope_rules import should_force_full_render, get_effective_render_mode


class TestForceFullRender:
    """Tests for should_force_full_render function."""

    def test_all_tasks_not_started_forces_full(self):
        """When all tasks are NOT_STARTED, force full render."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Task 1",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                ),
                MCPScopeTask(
                    designator="T-2",
                    name="Task 2",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert should_force_full_render(response) is True

    def test_any_task_started_no_force(self):
        """When any task is not NOT_STARTED, don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Task 1",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                ),
                MCPScopeTask(
                    designator="T-2",
                    name="Task 2",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert should_force_full_render(response) is False

    def test_nested_task_started_no_force(self):
        """When nested subtask is started, don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Parent",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Child",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                        )
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is False

    def test_all_nested_not_started_forces_full(self):
        """When all tasks including nested are NOT_STARTED, force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Parent",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Child",
                            status=TaskStatus.NOT_STARTED,
                            type=TaskType.CODE,
                        )
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is True

    def test_empty_tasks_no_force(self):
        """Empty task list doesn't force full."""
        response = MCPScopeResponse(tasks=[])

        assert should_force_full_render(response) is False

    def test_done_task_no_force(self):
        """Done tasks don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Done Task",
                    status=TaskStatus.DONE,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert should_force_full_render(response) is False


class TestGetEffectiveRenderMode:
    """Tests for get_effective_render_mode function."""

    def test_explicit_full_returns_full(self):
        """When full=True, always return FULL."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Task",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert get_effective_render_mode(response, full=True) == ScopeRenderMode.FULL

    def test_rules_force_full(self):
        """When rules trigger, return FULL even if full=False."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Task",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert get_effective_render_mode(response, full=False) == ScopeRenderMode.FULL

    def test_no_force_returns_compact(self):
        """When no rules trigger and full=False, return COMPACT."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Task",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert get_effective_render_mode(response, full=False) == ScopeRenderMode.COMPACT


class TestSiblingRule:
    """Tests for the sibling rule: force full if all focus task siblings are NOT_STARTED."""

    def test_all_siblings_not_started_forces_full(self):
        """When all siblings of focus task are NOT_STARTED, force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Parent",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Sibling 1 (focus)",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                            workflow_info=MCPWorkflowInfo(in_focus=True),
                        ),
                        MCPScopeTask(
                            designator="T-1.2",
                            name="Sibling 2",
                            status=TaskStatus.NOT_STARTED,
                            type=TaskType.CODE,
                        ),
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is True

    def test_one_sibling_in_progress_no_force(self):
        """When one sibling is IN_PROGRESS, don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Parent",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Sibling 1 (in progress)",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                        ),
                        MCPScopeTask(
                            designator="T-1.2",
                            name="Sibling 2 (focus)",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                            workflow_info=MCPWorkflowInfo(in_focus=True),
                        ),
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is False

    def test_one_sibling_done_no_force(self):
        """When one sibling is DONE, don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Parent",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Sibling 1 (done)",
                            status=TaskStatus.DONE,
                            type=TaskType.CODE,
                        ),
                        MCPScopeTask(
                            designator="T-1.2",
                            name="Sibling 2 (focus)",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                            workflow_info=MCPWorkflowInfo(in_focus=True),
                        ),
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is False

    def test_root_level_siblings_not_started_forces_full(self):
        """When focus is at root level and all root siblings are NOT_STARTED, force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Root 1 (focus)",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    workflow_info=MCPWorkflowInfo(in_focus=True),
                ),
                MCPScopeTask(
                    designator="T-2",
                    name="Root 2",
                    status=TaskStatus.NOT_STARTED,
                    type=TaskType.CODE,
                ),
            ]
        )

        assert should_force_full_render(response) is True

    def test_root_level_one_done_no_force(self):
        """When one root sibling is DONE, don't force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Root 1 (done)",
                    status=TaskStatus.DONE,
                    type=TaskType.CODE,
                ),
                MCPScopeTask(
                    designator="T-2",
                    name="Root 2 (focus)",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    workflow_info=MCPWorkflowInfo(in_focus=True),
                ),
            ]
        )

        assert should_force_full_render(response) is False

    def test_deeply_nested_focus_siblings_not_started(self):
        """When deeply nested focus task has all NOT_STARTED siblings, force full."""
        response = MCPScopeResponse(
            tasks=[
                MCPScopeTask(
                    designator="T-1",
                    name="Root",
                    status=TaskStatus.IN_PROGRESS,
                    type=TaskType.CODE,
                    subtasks=[
                        MCPScopeTask(
                            designator="T-1.1",
                            name="Middle",
                            status=TaskStatus.IN_PROGRESS,
                            type=TaskType.CODE,
                            subtasks=[
                                MCPScopeTask(
                                    designator="T-1.1.1",
                                    name="Deep 1 (focus)",
                                    status=TaskStatus.IN_PROGRESS,
                                    type=TaskType.CODE,
                                    workflow_info=MCPWorkflowInfo(in_focus=True),
                                ),
                                MCPScopeTask(
                                    designator="T-1.1.2",
                                    name="Deep 2",
                                    status=TaskStatus.NOT_STARTED,
                                    type=TaskType.CODE,
                                ),
                            ],
                        ),
                    ],
                ),
            ]
        )

        assert should_force_full_render(response) is True
