"""Pydantic models for MCP (Model-Controller-Presenter) response structures."""

from typing import List, Optional, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field
from src.nautex.api.scope_context_model import ScopeContext, ScopeTask, ScopeContextMode, TaskStatus, TaskType


class MCPScopeTask(BaseModel):
    designator: str = Field(..., description="Unique task identifier like PRD-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: str = Field(..., description="Current task status")
    requirements: List[str] = Field(default_factory=list, description="List of requirement designators")
    files: List[str] = Field(default_factory=list, description="List of file paths to manage according to the task")
    instructions: str = Field("", description="Instructions for this task") # TODO this is instructrion must be feel by context (heursitc func) and fur focus task it must be implementation instruction
    context_note: str = Field("", description="Additional context for this task state") # TODO this is must be optional and filled for context tasks 


class MCPScopeResponse(BaseModel):
    """Root model for MCP scope response."""
    progress_context: str = Field("", description="Overall instructions of what is going on") # TODO fill it depending on scope context mode
    instructions: str = Field("", description="Instructions based on the current context scope mode") # TODO fill it depending on scope context mode

    context_tasks: List[MCPScopeTask] = Field(default_factory=list, description="List of tasks to better understand context") # TODO put here all tasks that are not if focus, create function for fill context_note by heuristics. implement heursitic putting infro in context about position in tree (if any), also fill instruction by heursitcs function
    focus_tasks: List[MCPScopeTask] = Field(default_factory=dict, description="List of tasks to be focused on") # TODO put here tashs with deisgrangros in focus list



def is_status_equal(task_status, status_enum):
    """Compare task status with a TaskStatus enum value.

    Args:
        task_status: The task status to compare
        status_enum: The TaskStatus enum value to compare with

    Returns:
        True if the task status equals the enum value, False otherwise
    """
    # Simply compare the enum values directly
    return task_status == status_enum


def get_task_type_description(task: ScopeTask) -> str:
    """Generate a description of the task type.

    Args:
        task: The task to generate a type description for

    Returns:
        A string describing the task type, or empty string if task has no type
    """
    if not hasattr(task, 'type'):
        return ""

    return f"Task type: {task.type.value}."


def get_task_instructions(task: ScopeTask) -> str:
    """Generate instructions for a task based on its status and other properties.

    Args:
        task: The task to generate instructions for

    Returns:
        A string containing instructions for the task
    """
    if is_status_equal(task.status, TaskStatus.NOT_STARTED):
        return "This task is not started yet. Review requirements and files before beginning work."

    elif is_status_equal(task.status, TaskStatus.IN_PROGRESS):
        if task.subtasks:
            return "This task is in progress. Focus on completing subtasks in order."
        else:
            return "This task is in progress. Continue implementation according to requirements."

    elif is_status_equal(task.status, TaskStatus.DONE):
        return "This task is completed. No further action needed."

    elif is_status_equal(task.status, TaskStatus.BLOCKED):
        return "This task is blocked. Resolve blocking issues before continuing."

    return ""



def get_mode_instructions(mode: ScopeContextMode) -> str:
    """Generate instructions based on the scope context mode.

    Args:
        mode: The current scope context mode

    Returns:
        A string containing instructions for the current mode
    """
    if mode == ScopeContextMode.ExecuteSubtasks:
        return "Execute subtasks in order. Complete all subtasks before marking the parent task as done."

    elif mode == ScopeContextMode.FinalizeMasterTask:
        return "All subtasks are completed. Review and finalize the master task."

    return ""


def compose_context_task_note(task: ScopeTask) -> str:
    """Compose a context note for a context task.

    Args:
        task: The task to compose a context note for

    Returns:
        A string containing the context note
    """
    notes = []

    # Add task type information if available
    type_info = get_task_type_description(task)
    if type_info:
        notes.append(type_info)

    # Add subtask information if available
    if task.subtasks:
        subtask_designators = [subtask.task_designator for subtask in task.subtasks]
        if len(subtask_designators) == 1:
            notes.append(f"Has subtask: {subtask_designators[0]}")
        else:
            notes.append(f"Has subtasks: {', '.join(subtask_designators)}")

    # Add a note about this being a context task
    notes.append("Consider this task for your information for the scope of focus tasks.")

    return " ".join(notes)


def create_mcp_task_from_scope_task(task: ScopeTask, is_focus: bool) -> MCPScopeTask:
    """Create an MCPScopeTask from a ScopeTask.

    Args:
        task: The ScopeTask to convert
        is_focus: Whether this task is a focus task

    Returns:
        An MCPScopeTask containing the converted data
    """
    # Create the basic task state
    task_state = MCPScopeTask(
        designator=task.task_designator,
        name=task.name,
        description=task.description,
        status=task.status.value,
        requirements=[req.requirement_designator for req in task.requirements if req.requirement_designator],
        files=[file.file_path for file in task.files]
    )

    # Fill instructions based on task status
    task_state.instructions = get_task_instructions(task)

    # Fill context_note for context tasks
    if not is_focus:
        task_state.context_note = compose_context_task_note(task)

    return task_state


def convert_scope_context_to_mcp_response(scope_context: ScopeContext, base_path: Optional[str] = None) -> MCPScopeResponse:
    """Convert a ScopeContext to an MCPScopeResponse.

    Args:
        scope_context: The scope context to convert
        base_path: Optional base path for rendering relative file paths

    Returns:
        An MCPScopeResponse containing the converted data
    """
    # Create the response object
    response = MCPScopeResponse()

    # Fill progress_context and instructions based on scope context mode
    response.progress_context = f"Current mode: {scope_context.mode.value}"
    response.instructions = get_mode_instructions(scope_context.mode)

    # Process all tasks recursively
    focus_tasks = []
    context_tasks = []

    def process_task(task: ScopeTask, is_focus: bool = False):
        # Create MCPScopeTask from ScopeTask using the helper function
        task_state = create_mcp_task_from_scope_task(task, is_focus)

        # Add to appropriate list
        if is_focus:
            focus_tasks.append(task_state)
        else:
            context_tasks.append(task_state)

        # Process subtasks
        for subtask in task.subtasks:
            # A subtask is in focus if its designator is in the focus_tasks list
            subtask_in_focus = subtask.task_designator in scope_context.focus_tasks
            process_task(subtask, subtask_in_focus)

    # Process all top-level tasks
    for task in scope_context.tasks:
        # A task is in focus if its designator is in the focus_tasks list
        task_in_focus = task.task_designator in scope_context.focus_tasks
        process_task(task, task_in_focus)

    # Set the focus and context tasks in the response
    response.focus_tasks = focus_tasks
    response.context_tasks = context_tasks

    return response
