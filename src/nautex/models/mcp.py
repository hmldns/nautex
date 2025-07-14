"""Pydantic models for MCP (Model-Controller-Presenter) response structures."""

from typing import List, Optional, Dict, Any, Union, Tuple
from enum import Enum
from pydantic import BaseModel, Field
from ..api.scope_context_model import ScopeContext, ScopeTask, ScopeContextMode, TaskStatus, TaskType


class MCPScopeTask(BaseModel):
    designator: str = Field(..., description="Unique task identifier like PRD-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    type: TaskType = Field(..., description="Task type (Code, Review, Test, Input)")
    requirements: List[str] = Field(default_factory=list, description="List of requirement designators")
    files: List[str] = Field(default_factory=list, description="List of file paths to manage according to the task")
    context_note: Optional[str] = Field(None, description="Additional context for this task state")
    instructions: Optional[str] = Field(None, description="Instructions for this task")
    in_focus: bool = Field(False, description="Whether this task is in focus")
    subtasks: List["MCPScopeTask"] = Field(default_factory=list, description="List of subtasks")


class MCPScopeResponse(BaseModel):
    """Root model for MCP scope response."""
    progress_context: str = Field("", description="Overall instructions of what is going on")
    instructions: str = Field("", description="Instructions based on the current context scope mode")
    documents_paths: Dict[str, str] = Field(default_factory=dict, description="Map of document designators to paths") 
    tasks: List[MCPScopeTask] = Field(default_factory=list, description="List of tasks in a tree structure")

MCPScopeTask.model_rebuild()


def get_mode_instructions(mode: ScopeContextMode) -> str:
    """Generate instructions based on the scope context mode.

    Args:
        mode: The current scope context mode

    Returns:
        A string containing instructions for the current mode
    """
    if mode == ScopeContextMode.ExecuteSubtasks:
        return f"Follow instructions on tasks, execute needed. On starting set relevant tasks state in \"{TaskStatus.IN_PROGRESS}\" state and \"{TaskStatus.DONE}\" when finished and tested."

    elif mode == ScopeContextMode.FinalizeMasterTask:
        return f"All subtasks are completed. Review and finalize results of the implementation and move master task to \"{TaskStatus.DONE}\" state."

    return ""


def create_mcp_task_from_scope_task(task: ScopeTask, is_in_focus: bool = False) -> MCPScopeTask:
    """Create an MCPScopeTask from a ScopeTask.

    Args:
        task: The ScopeTask to convert
        is_in_focus: Whether this task is a focus task

    Returns:
        An MCPScopeTask containing the converted data
    """
    # Create the basic task state
    task_state = MCPScopeTask(
        designator=task.task_designator,
        name=task.name,
        description=task.description,
        status=task.status,
        type=task.type,
        requirements=[req.requirement_designator for req in task.requirements if req.requirement_designator],
        files=[file.file_path for file in task.files],
        subtasks=[],  # Will be filled later
        in_focus=is_in_focus
    )

    return task_state


def get_task_instruction(status: TaskStatus, type: TaskType, mode: ScopeContextMode, is_in_focus: bool, has_subtasks: bool) -> Tuple[str, str]:
    """Provides context and instructions for a task based on its state and the execution mode."""
    # --- Repetitive String Constants for Instructions and Notes ---
    NOTE_IRRELEVANT_TASK = "This task is provided for scope context awareness. "

    INST_SUBTASKS = "Execute subtasks."

    INST_START_CODING = "Implement the required files changes for this task. "
    INST_CONTINUE_CODING = "Continue the implementation of this coding task. "
    INST_START_REVIEW = "Guide user through results review for the scope tasks. "
    INST_CONTINUE_REVIEW = "Continue reviewing process with user, gaining feedback from them. "
    INST_START_TESTING = "Test the implementation of the tasks in the scope according to the requirements and tasks. "
    INST_CONTINUE_TESTING = "Continue testing of the tasks in the scope according to the requirements and tasks. "
    INST_PROVIDE_INPUT = "Provide the required input data and info from user for this task. "
    INST_CONTINUE_FOR_INPUT = "Request and process required input data and info from user. "

    INST_FINALIZE_MASTER_TASK = "All subtasks are complete. Finalize the master task by integrating the work, reviewing and testing subtasks in scope. "
    INST_CONTINUE_FINALIZE_MASTER_TASK = "Continue finalizing the master task via assessing subtasks. "

    INST_TASK_DONE = "Completed task."
    INST_TASK_BLOCKED = "This task is blocked. Address the blocking issues before proceeding. "

    # --- Lookup Table for Task Instructions ---
    # The table is structured as: (status, type, mode) -> (context_note, instruction)
    # This table assumes the task is in focus (is_in_focus=True).
    in_focus_instruction_map = {
        # --- Mode: ExecuteSubtasks ---
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                    INST_START_CODING),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                    INST_CONTINUE_CODING),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                      INST_START_REVIEW),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                      INST_START_REVIEW + INST_CONTINUE_REVIEW),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                    INST_START_TESTING),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                    INST_CONTINUE_TESTING),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                     INST_PROVIDE_INPUT),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): ("",
                                                                                     INST_CONTINUE_FOR_INPUT),

        # --- Mode: FinalizeMasterTask ---
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("",
                                                                                       INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("",
                                                                                         INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("",
                                                                                       INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", INST_PROVIDE_INPUT),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", INST_CONTINUE_FOR_INPUT),
    }

    if status == TaskStatus.BLOCKED:
        return ("", INST_TASK_BLOCKED)

    # Then check if the task is not in focus
    if not is_in_focus:
        if has_subtasks:
            return NOTE_IRRELEVANT_TASK, INST_SUBTASKS
        else:
            return NOTE_IRRELEVANT_TASK, ""

    # Finally, look up instructions for in-focus tasks
    key = (status, type, mode)
    context_note, instructions = in_focus_instruction_map.get(key, ("", ""))

    if status == TaskStatus.DONE:
        instructions = ""

    return context_note, instructions


def set_context_info_and_notes(mcp_task: MCPScopeTask, scope_context: ScopeContext) -> None:
    # Revisit mcp_tasks for setting context and instructions
    finalize_master_task = scope_context.mode == ScopeContextMode.FinalizeMasterTask
    tasks_execution = scope_context.mode == ScopeContextMode.ExecuteSubtasks

    def _set_context_info(_mcp_task: MCPScopeTask) -> None:
        _mcp_task.context_note, _mcp_task.instructions = get_task_instruction(_mcp_task.status, _mcp_task.type,
                                                                              scope_context.mode,
                                                                              _mcp_task.in_focus,
                                                                              bool(_mcp_task.subtasks))

    def traverse_tasks(_mcp_task: MCPScopeTask) -> None:
        _set_context_info(_mcp_task)
        for subtask in _mcp_task.subtasks:
            traverse_tasks(subtask)

    traverse_tasks(mcp_task)


def convert_scope_context_to_mcp_response(scope_context: ScopeContext, documents_paths: Dict[str, str],
                                          base_path: Optional[str] = None) -> MCPScopeResponse:
    """Convert a ScopeContext to an MCPScopeResponse.

    Args:
        scope_context: The scope context to convert
        documents_paths: Map of document designators to paths
        base_path: Optional base path for rendering relative file paths

    Returns:
        An MCPScopeResponse containing the converted data
    """
    # Create the response object

    # Process all tasks recursively to build the task tree
    task_map = {}  # Map of designator to MCPScopeTask

    def process_scope_task(task: ScopeTask) -> MCPScopeTask:
        # Create MCPScopeTask from ScopeTask using the helper function
        is_in_focus = task.task_designator in scope_context.focus_tasks
        mcp_task = create_mcp_task_from_scope_task(task, is_in_focus)

        task_map[task.task_designator] = mcp_task

        for subtask in task.subtasks:
            subtask_state = process_scope_task(subtask)
            mcp_task.subtasks.append(subtask_state)

        return mcp_task

    # Process all top-level tasks
    top_level_tasks = []
    for task in scope_context.tasks:
        # A task is in focus if its designator is in the focus_tasks list
        top_level_task = process_scope_task(task)
        set_context_info_and_notes(top_level_task, scope_context)
        top_level_tasks.append(top_level_task)

    progress_context = f"You are in the process of executing tasks of the project with provided scope below" \
                        if top_level_tasks else \
                        "Implementation plan is complete. Report completion. "

    response = MCPScopeResponse(
        progress_context=progress_context,
        instructions=get_mode_instructions(scope_context.mode) if top_level_tasks else "",
        documents_paths=documents_paths,
        tasks=top_level_tasks
    )

    return response


class MCPTaskOperation(BaseModel):
    """Model representing a single operation on a task for MCP."""
    task_designator: str = Field(..., description="Unique task identifier like TASK-123")
    updated_status: Optional[TaskStatus] = Field(None, description="New status for the task")
    updated_type: Optional[TaskType] = Field(None, description="New type for the task")
    new_note: Optional[str] = Field(None, description="New note content to add to the task")


class MCPTaskUpdateRequest(BaseModel):
    """Request model for batch task operations in MCP."""
    operations: List[MCPTaskOperation] = Field(..., description="List of operations to perform")


class MCPTaskUpdateResponse(BaseModel):
    """Response model for batch task operations in MCP."""
    success: bool = Field(..., description="Whether the operation was successful")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data payload")
    message: Optional[str] = Field(None, description="Human-readable message")
    error: Optional[str] = Field(None, description="Error message if success is False")
