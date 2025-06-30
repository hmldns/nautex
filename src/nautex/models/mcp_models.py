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
    context_note: Optional[str] = Field(None, description="Additional context for this task state")
    instructions: Optional[str] = Field(None, description="Instructions for this task")
    subtasks: List["MCPScopeTask"] = Field(default_factory=list, description="List of subtasks")


class MCPScopeResponse(BaseModel):
    """Root model for MCP scope response."""
    progress_context: str = Field("", description="Overall instructions of what is going on")
    instructions: str = Field("", description="Instructions based on the current context scope mode")
    tasks: List[MCPScopeTask] = Field(default_factory=list, description="List of tasks in a tree structure")

MCPScopeTask.model_rebuild()

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
    if task.status == TaskStatus.NOT_STARTED:
        return "This task is not started yet. Review requirements and files before beginning work."

    elif task.status == TaskStatus.IN_PROGRESS:
        if task.subtasks:
            return "This task is in progress. Focus on completing subtasks in order."
        else:
            return "This task is in progress. Continue implementation according to requirements."

    elif task.status == TaskStatus.DONE:
        return "This task is completed. No further action needed."

    elif task.status == TaskStatus.BLOCKED:
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
        files=[file.file_path for file in task.files],
        subtasks=[]  # Will be filled later
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

    # Process all tasks recursively to build the task tree
    task_map = {}  # Map of designator to MCPScopeTask

    def process_task(task: ScopeTask, is_focus: bool = False) -> MCPScopeTask:
        # Create MCPScopeTask from ScopeTask using the helper function
        task_state = create_mcp_task_from_scope_task(task, is_focus)
        
        # Store in map for later reference
        task_map[task.task_designator] = task_state
        
        # Process subtasks and add them to the task's subtasks list
        for subtask in task.subtasks:
            # A subtask is in focus if its designator is in the focus_tasks list
            subtask_in_focus = subtask.task_designator in scope_context.focus_tasks
            subtask_state = process_task(subtask, subtask_in_focus)
            task_state.subtasks.append(subtask_state)
        
        return task_state

    # Process all top-level tasks
    top_level_tasks = []
    for task in scope_context.tasks:
        # A task is in focus if its designator is in the focus_tasks list
        task_in_focus = task.task_designator in scope_context.focus_tasks
        top_level_task = process_task(task, task_in_focus)
        top_level_tasks.append(top_level_task)

    # Set the tasks in the response
    response.tasks = top_level_tasks

    return response

