"""Pydantic models for MCP (Model-Controller-Presenter) response structures."""

from typing import List, Optional, Dict, Any, Union, Tuple
from enum import Enum
from pydantic import BaseModel, Field
from src.nautex.api.scope_context_model import ScopeContext, ScopeTask, ScopeContextMode, TaskStatus, TaskType


class MCPScopeTask(BaseModel):
    designator: str = Field(..., description="Unique task identifier like PRD-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
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


def create_mcp_task_from_scope_task(task: ScopeTask) -> MCPScopeTask:
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

    return task_state


def get_task_instruction(status: TaskStatus, type: TaskType, mode: ScopeContextMode, is_in_focus: bool) -> Tuple[str, str]:
    """
    Provides context and instructions for a task based on its state and the execution mode.

    Args:
        status: The current status of the task.
        type: The type of the task.
        mode: The current scope execution mode.
        is_in_focus: A boolean indicating if the task is the current focus.

    Returns:
        A tuple containing the context note and the instruction string.
    """
    # --- Repetitive String Constants for Instructions and Notes ---
    AWAIT_SUBTASK_COMPLETION_NOTE = "This is a master task awaiting completion of its subtasks."
    SUBTASK_CONTEXT_NOTE = "This is a subtask of a larger master task."
    IRRELEVANT_TASK_NOTE = "This task is not currently in focus and is provided for context only."

    START_CODING_INST = "Implement the required code changes for this task."
    CONTINUE_CODING_INST = "Continue the implementation of this coding task."
    START_REVIEW_INST = "Review the code associated with this task."
    CONTINUE_REVIEW_INST = "Continue reviewing the code for this task."
    START_TESTING_INST = "Test the implementation of this task based on the requirements."
    CONTINUE_TESTING_INST = "Continue testing the implementation."
    PROVIDE_INPUT_INST = "Provide the required input or feedback for this task."
    WAIT_FOR_INPUT_INST = "Awaiting user input to proceed."

    FINALIZE_MASTER_TASK_INST = "All subtasks are complete. Finalize the master task by integrating the work and preparing for completion."
    CONTINUE_FINALIZE_MASTER_TASK_INST = "Continue finalizing the master task."

    TASK_DONE_INST = "This task is complete. No further action is needed."
    TASK_BLOCKED_INST = "This task is blocked. Address the blocking issues before proceeding."

    # --- Lookup Table for Task Instructions ---
    # The table is structured as: (status, type, mode) -> (context_note, instruction)
    # This table assumes the task is in focus (is_in_focus=True).
    instruction_map = {
        # --- Mode: ExecuteSubtasks ---
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, START_CODING_INST),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, CONTINUE_CODING_INST),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, START_REVIEW_INST),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, CONTINUE_REVIEW_INST),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, START_TESTING_INST),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, CONTINUE_TESTING_INST),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, PROVIDE_INPUT_INST),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): (SUBTASK_CONTEXT_NOTE, WAIT_FOR_INPUT_INST),

        # --- Mode: FinalizeMasterTask ---
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("", FINALIZE_MASTER_TASK_INST),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("", CONTINUE_FINALIZE_MASTER_TASK_INST),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("", FINALIZE_MASTER_TASK_INST),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("", CONTINUE_FINALIZE_MASTER_TASK_INST),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("", FINALIZE_MASTER_TASK_INST),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("", CONTINUE_FINALIZE_MASTER_TASK_INST),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", PROVIDE_INPUT_INST),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", WAIT_FOR_INPUT_INST),
    }

    if not is_in_focus:
        return (IRRELEVANT_TASK_NOTE, "")

    if status == TaskStatus.DONE:
        return ("", TASK_DONE_INST)
    if status == TaskStatus.BLOCKED:
        return ("", TASK_BLOCKED_INST)

    key = (status, type, mode)
    return instruction_map.get(key, ("", ""))


def set_context_info(mcp_tasks: ScopeTask, scope_context: ScopeContext) -> None:
    # Revisit mcp_tasks for setting context and instructions
    finalize_master_task = scope_context.mode == ScopeContextMode.FinalizeMasterTask
    tasks_execution = scope_context.mode == ScopeContextMode.ExecuteSubtasks
    focus_tasks_designators = {td for td in scope_context.focus_tasks}

    def _set_context_info(mcp_task: MCPScopeTask) -> None:
        mcp_task.instructions =

    pass


def convert_scope_context_to_mcp_response(scope_context: ScopeContext, base_path: Optional[str] = None) -> MCPScopeResponse:
    """Convert a ScopeContext to an MCPScopeResponse.

    Args:
        scope_context: The scope context to convert
        base_path: Optional base path for rendering relative file paths

    Returns:
        An MCPScopeResponse containing the converted data
    """
    # Create the response object

    # Process all tasks recursively to build the task tree
    task_map = {}  # Map of designator to MCPScopeTask

    def process_task(task: ScopeTask) -> MCPScopeTask:
        # Create MCPScopeTask from ScopeTask using the helper function
        mcp_task = create_mcp_task_from_scope_task(task)
        
        task_map[task.task_designator] = mcp_task
        
        for subtask in task.subtasks:
            subtask_state = process_task(subtask)
            mcp_task.subtasks.append(subtask_state)
        
        return mcp_task

    # Process all top-level tasks
    top_level_tasks = []
    for task in scope_context.tasks:
        # A task is in focus if its designator is in the focus_tasks list
        top_level_task = process_task(task)
        top_level_tasks.append(top_level_task)

    response = MCPScopeResponse(
        progress_context=f"Current mode: {scope_context.mode.value}",
        instructions=get_mode_instructions(scope_context.mode),
        tasks=top_level_tasks
    )

    return response
