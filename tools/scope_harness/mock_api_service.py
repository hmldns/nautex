"""Mock Nautex API service for testing MCP layer."""

from typing import Dict, List, Optional
from copy import deepcopy

from nautex.api.scope_context_model import (
    ScopeContext,
    ScopeTask,
    ScopeContextMode,
    TaskStatus,
    TaskType,
    RequirementReference,
    FileReference,
)
from nautex.api.api_models import APIResponse, TaskOperation
from nautex.services.nautex_api_protocol import NautexAPIProtocol


class MockNautexAPIService(NautexAPIProtocol):
    """Mock API service implementing NautexAPIProtocol.

    Provides hardcoded sample plan with local state management for testing.
    """

    def __init__(self):
        self._tasks: List[ScopeTask] = []
        self._focus_tasks: List[str] = []
        self._mode: ScopeContextMode = ScopeContextMode.ExecuteSubtasks
        self._load_sample_plan()

    def _load_sample_plan(self) -> None:
        """Load a sample plan for testing with simple incrementing designators."""
        # Leaf tasks under T-1
        t_2 = ScopeTask(
            task_designator="T-2",
            name="Setup database schema",
            description="Create the initial database schema for user management",
            status=TaskStatus.DONE,
            type=TaskType.CODE,
            requirements=[RequirementReference(requirement_designator="REQ-101")],
            files=[FileReference(file_path="src/db/schema.sql")],
        )

        t_3 = ScopeTask(
            task_designator="T-3",
            name="Implement user model",
            description="Create the User model class with validation",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            requirements=[RequirementReference(requirement_designator="REQ-102")],
            files=[FileReference(file_path="src/models/user.py")],
        )

        t_4 = ScopeTask(
            task_designator="T-4",
            name="Write user model tests",
            description="Unit tests for the User model",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.TEST,
            requirements=[RequirementReference(requirement_designator="REQ-102")],
            files=[FileReference(file_path="tests/test_user.py")],
        )

        t_5 = ScopeTask(
            task_designator="T-5",
            name="User API endpoints",
            description="Create REST API endpoints for user CRUD operations",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.CODE,
            requirements=[RequirementReference(requirement_designator="REQ-103")],
            files=[FileReference(file_path="src/api/users.py")],
        )

        t_6 = ScopeTask(
            task_designator="T-6",
            name="User management review",
            description="Review the user management implementation with stakeholders",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.REVIEW,
        )

        # Top-level task T-1
        t_1 = ScopeTask(
            task_designator="T-1",
            name="User Management",
            description="Implement complete user management functionality",
            status=TaskStatus.IN_PROGRESS,
            type=TaskType.CODE,
            subtasks=[t_2, t_3, t_4, t_5, t_6],
        )

        # Leaf tasks under T-7
        t_8 = ScopeTask(
            task_designator="T-8",
            name="Auth service setup",
            description="Setup authentication service infrastructure",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.CODE,
            files=[FileReference(file_path="src/services/auth.py")],
        )

        t_9 = ScopeTask(
            task_designator="T-9",
            name="JWT implementation",
            description="Implement JWT token generation and validation",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.CODE,
            requirements=[RequirementReference(requirement_designator="REQ-201")],
            files=[FileReference(file_path="src/auth/jwt.py")],
        )

        t_7 = ScopeTask(
            task_designator="T-7",
            name="Authentication System",
            description="Implement authentication and authorization",
            status=TaskStatus.NOT_STARTED,
            type=TaskType.CODE,
            subtasks=[t_8, t_9],
        )

        self._tasks = [t_1, t_7]
        self._recalculate_focus()

    def _recalculate_focus(self) -> None:
        """Recalculate which tasks should be in focus based on status.

        Focus selection logic:
        1. Find leaf tasks (no subtasks) that are NOT_STARTED or IN_PROGRESS
        2. Prioritize IN_PROGRESS tasks
        3. Select 1 task at a time
        """
        in_progress: List[str] = []
        not_started: List[str] = []

        def collect_actionable_tasks(task: ScopeTask) -> None:
            """Collect leaf tasks that are actionable."""
            if task.subtasks:
                for subtask in task.subtasks:
                    collect_actionable_tasks(subtask)
            else:
                # Leaf task
                if task.status == TaskStatus.IN_PROGRESS:
                    in_progress.append(task.task_designator)
                elif task.status == TaskStatus.NOT_STARTED:
                    not_started.append(task.task_designator)

        for task in self._tasks:
            collect_actionable_tasks(task)

        # Prioritize IN_PROGRESS, then NOT_STARTED
        focus_candidates = in_progress + not_started

        # Select 1 focus task at a time (realistic behavior)
        self._focus_tasks = focus_candidates[:1]

        # Determine mode
        if self._all_subtasks_done():
            self._mode = ScopeContextMode.FinalizeMasterTask
        else:
            self._mode = ScopeContextMode.ExecuteSubtasks

    def _all_subtasks_done(self) -> bool:
        """Check if all leaf subtasks are done."""
        def check_task(task: ScopeTask) -> bool:
            if task.subtasks:
                return all(check_task(st) for st in task.subtasks)
            return task.status == TaskStatus.DONE

        return all(check_task(t) for t in self._tasks)

    def _find_task(self, designator: str) -> Optional[ScopeTask]:
        """Find a task by its designator."""
        def search(task: ScopeTask) -> Optional[ScopeTask]:
            if task.task_designator == designator:
                return task
            for subtask in task.subtasks:
                found = search(subtask)
                if found:
                    return found
            return None

        for task in self._tasks:
            found = search(task)
            if found:
                return found
        return None

    async def next_scope(
        self, project_id: str, plan_id: str, from_mcp: bool = False
    ) -> Optional[ScopeContext]:
        """Get the current scope context.

        Args:
            project_id: The project ID (used in response)
            plan_id: The plan ID (ignored for mock)
            from_mcp: Whether request is from MCP (ignored for mock)

        Returns:
            The current scope context
        """
        return ScopeContext(
            tasks=deepcopy(self._tasks),
            project_id=project_id,
            mode=self._mode,
            focus_tasks=self._focus_tasks.copy(),
        )

    async def update_tasks(
        self, project_id: str, plan_id: str,
        operations: List[TaskOperation], from_mcp: bool = False
    ) -> APIResponse:
        """Update tasks based on operations.

        Args:
            project_id: The project ID (ignored for mock)
            plan_id: The plan ID (ignored for mock)
            operations: List of task operations to apply
            from_mcp: Whether request is from MCP (ignored for mock)

        Returns:
            APIResponse with success status
        """
        for op in operations:
            task = self._find_task(op.task_designator)
            if task and op.updated_status:
                task.status = op.updated_status

        self._recalculate_focus()
        return APIResponse(status="success", message=f"Updated {len(operations)} tasks")

    def reset(self) -> None:
        """Reset to initial state."""
        self._load_sample_plan()

    def get_all_task_designators(self) -> List[tuple]:
        """Get all task designators for TUI display.

        Returns:
            List of (designator, name, status, depth) tuples
        """
        result = []

        def collect(task: ScopeTask, depth: int = 0) -> None:
            result.append((task.task_designator, task.name, task.status, depth))
            for subtask in task.subtasks:
                collect(subtask, depth + 1)

        for task in self._tasks:
            collect(task)

        return result

    def is_focus_task(self, designator: str) -> bool:
        """Check if a task is in focus."""
        return designator in self._focus_tasks

    def get_tasks_as_scope_data(self) -> List[dict]:
        """Export tasks in scope response format for tree state init.

        Returns:
            List of task dicts matching scope response format
        """
        def to_dict(task: ScopeTask) -> dict:
            return {
                "designator": task.task_designator,
                "name": task.name,
                "status": task.status.value,
                "workflow_info": {"in_focus": task.task_designator in self._focus_tasks},
                "subtasks": [to_dict(st) for st in task.subtasks]
            }
        return [to_dict(t) for t in self._tasks]
