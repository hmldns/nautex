"""Pydantic models for MCP (Model-Controller-Presenter) response structures."""

from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING
from enum import Enum
from pydantic import BaseModel, Field

# Try to import from scope_context_model, but provide type hints if it fails
try:
    from src.nautex.api.scope_context_model import ScopeContext, ScopeTask, ScopeContextMode, TaskStatus
except ImportError:
    # For type checking only
    if TYPE_CHECKING:
        from src.nautex.api.scope_context_model import ScopeContext, ScopeTask, ScopeContextMode, TaskStatus



class MCPTaskState(BaseModel):
    designator: str = Field(..., description="Unique task identifier like TASK-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: str = Field(..., description="Current task status")
    requirements: List[str] = Field(default_factory=list, description="List of requirement designators")
    files: List[str] = Field(default_factory=list, description="List of file paths")
    instructions: str = Field("", description="Additional instructions for this task state") # TODO this is instructrion must be feel by context (heursitc func) and fur focus task it must be implementation instruction
    context_note: str = Field("", description="Additional context for this task state") # TODO this is must be optional and filled for context tasks 


class MCPScopeResponse(BaseModel):
    """Root model for MCP scope response."""
    progress_context: str = Field("", description="Instructions based on the current mode") # TODO fill it depending on scope context mode
    instructions: str = Field("", description="Instructions based on the current mode") # TODO fill it depending on scope context mode

    context_tasks: List[MCPTaskState] = Field(default_factory=list, description="List of task designators to focus on") # TODO put here all tasks that are not if focus, create function for fill context_note by heuristics. implement heursitic putting infro in context about position in tree (if any), also fill instruction by heursitcs function
    focus_tasks: List[MCPTaskState] = Field(default_factory=dict, description="Map of task designators to task states") # TODO put here tashs with deisgrangros in focus list



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


def convert_scope_context_to_mcp_response(scope_context: ScopeContext, base_path: Optional[str] = None) -> MCPScopeResponse:
    """Convert a ScopeContext to an MCPScopeResponse.

    Args:
        scope_context: The scope context to convert
        base_path: Optional base path for rendering relative file paths

    Returns:
        An MCPScopeResponse representing the scope context
    """
    # Create the base response
    response = MCPScopeResponse(
        project_id=scope_context.project_id,
        mode=scope_context.mode.value,
        focus_tasks=scope_context.focus_tasks,
        mode_instructions=get_mode_instructions(scope_context.mode)
    )

    # Generate the textual representation
    response.textual_representation = scope_context.render_as_plain_text(base_path)

    # Process all tasks
    task_dict = {}

    def process_task(task: ScopeTask):
        # Create MCPTaskState for this task
        subtask_designators = [subtask.task_designator for subtask in task.subtasks]
        requirement_designators = [req.requirement_designator for req in task.requirements if req.requirement_designator]
        file_paths = [file.file_path for file in task.files]

        # Generate task-specific instructions
        instructions = get_task_instructions(task)

        task_state = MCPTaskState(
            task_designator=task.task_designator,
            name=task.name,
            description=task.description,
            status=task.status.value,
            requirements=requirement_designators,
            files=file_paths,
            subtasks=subtask_designators,
            instructions=instructions
        )

        # Add to the dictionary
        task_dict[task.task_designator] = task_state

        # Process subtasks recursively
        for subtask in task.subtasks:
            process_task(subtask)

    # Process all top-level tasks
    for task in scope_context.tasks:
        process_task(task)

    # Set the tasks dictionary in the response
    response.tasks = task_dict

    return response
