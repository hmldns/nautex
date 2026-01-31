"""Rules for forcing full scope rendering."""

from typing import Optional, Tuple

from nautex.api.scope_context_model import TaskStatus

from .mcp import MCPScopeResponse, MCPScopeTask, ScopeRenderMode


def _all_tasks_not_started(tasks: list[MCPScopeTask]) -> bool:
    """Recursively check if all tasks have NOT_STARTED status."""
    for task in tasks:
        if task.status != TaskStatus.NOT_STARTED:
            return False
        # Check subtasks recursively
        if task.subtasks and not _all_tasks_not_started(task.subtasks):
            return False
    return True


def _find_first_focus_task_with_parent(
    tasks: list[MCPScopeTask],
    parent: Optional[MCPScopeTask] = None
) -> Tuple[Optional[MCPScopeTask], Optional[MCPScopeTask]]:
    """Find the first focus task and its parent.

    Args:
        tasks: List of tasks to search
        parent: Parent of these tasks (None for root level)

    Returns:
        Tuple of (focus_task, parent_task). Parent is None if focus is at root level.
    """
    for task in tasks:
        if task.workflow_info and task.workflow_info.in_focus:
            return task, parent
        # Search in subtasks
        if task.subtasks:
            result = _find_first_focus_task_with_parent(task.subtasks, task)
            if result[0]:
                return result
    return None, None


def _all_siblings_not_started(focus_task: MCPScopeTask, parent: Optional[MCPScopeTask], root_tasks: list[MCPScopeTask]) -> bool:
    """Check if all siblings of the focus task are NOT_STARTED.

    Args:
        focus_task: The focus task
        parent: Parent of the focus task (None if root level)
        root_tasks: Root level tasks (used when parent is None)

    Returns:
        True if all siblings (excluding focus task) are NOT_STARTED
    """
    # Get siblings: either parent's subtasks or root tasks
    siblings = parent.subtasks if parent else root_tasks

    for sibling in siblings:
        # Skip the focus task itself
        if sibling.designator == focus_task.designator:
            continue
        if sibling.status != TaskStatus.NOT_STARTED:
            return False
    return True


def should_force_full_render(response: MCPScopeResponse) -> bool:
    """Determine if full rendering should be forced based on scope content.

    Rules:
    1. Force full if all tasks are "Not started" (fresh scope, user needs context)
    2. Force full if all siblings of the first focus task are "Not started" (new section)

    Args:
        response: The MCPScopeResponse to evaluate

    Returns:
        True if full rendering should be forced
    """
    if not response.tasks:
        return False

    # Rule 1: All tasks are "Not started" -> force full render
    if _all_tasks_not_started(response.tasks):
        return True

    # Rule 2: All siblings of first focus task are "Not started" -> force full render
    focus_task, parent = _find_first_focus_task_with_parent(response.tasks)
    if focus_task and _all_siblings_not_started(focus_task, parent, response.tasks):
        return True

    return False


def get_effective_render_mode(response: MCPScopeResponse, full: bool = False) -> ScopeRenderMode:
    """Get the effective render mode after applying rules.

    Args:
        response: The MCPScopeResponse to evaluate
        full: Explicitly requested full mode

    Returns:
        ScopeRenderMode.FULL if full requested or rules force it, else COMPACT
    """
    if full or should_force_full_render(response):
        return ScopeRenderMode.FULL
    return ScopeRenderMode.COMPACT
