"""Sample script to generate ScopeContext instances and convert them to MCP responses."""

import json
import os
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

# Define models directly in this file to avoid import issues

# --- Models from scope_context_model.py ---

class TaskStatus(str, Enum):
    NOT_STARTED = "Not started"
    IN_PROGRESS = "In progress"
    DONE = "Done"
    BLOCKED = "Blocked"


class TaskType(str, Enum):
    CODE = "Code"
    REVIEW = "Review"
    TEST = "Test"
    INPUT = "Input"


class ScopeContextMode(str, Enum):
    """Enum for the state of a scope context."""
    ExecuteSubtasks = "ExecuteSubtasks"
    FinalizeMasterTask = "FinalizeMasterTask"


class Reference(BaseModel):
    """Base class for all references."""
    root_id: Optional[str] = Field(None, description="Root document ID", exclude=True)
    item_id: Optional[str] = Field(None, description="Item ID", exclude=True)


class TaskReference(Reference):
    """Reference to a task by its designator."""
    task_designator: Optional[str] = Field(None, description="Unique task identifier like TASK-123")


class RequirementReference(Reference):
    """Reference to a requirement by its designator."""
    requirement_designator: Optional[str] = Field(None, description="Unique requirement identifier like REQ-45")


class FileReference(Reference):
    """Reference to a file by its path."""
    file_path: str = Field(..., description="Path to the file")


class ScopeTask(BaseModel):
    """Task model for scope context with subtasks and references."""
    task_designator: str = Field(..., description="Unique task identifier like TASK-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    type: TaskType = Field(..., description="Type of the task (Code, Review, Test, Input)")
    subtasks: List["ScopeTask"] = Field(default_factory=list, description="List of subtasks")
    requirements: List[RequirementReference] = Field(default_factory=list, description="List of requirement references")
    files: List[FileReference] = Field(default_factory=list, description="List of file references")


class ScopeContext(BaseModel):
    """Root model for scope context representing a tasks tree fragment."""
    tasks: List[ScopeTask] = Field(default_factory=list, description="List of tasks in the scope")
    project_id: Optional[str] = Field(None, description="Project identifier")
    mode: ScopeContextMode = Field(..., description="Current state of the scope context")
    focus_tasks: List[str] = Field(default_factory=list, description="List of task designators to focus on")


# --- Models from mcp_models.py ---

class MCPScopeTask(BaseModel):
    designator: str = Field(..., description="Unique task identifier like PRD-123")
    name: str = Field(..., description="Human-readable task name")
    description: Optional[str] = Field(None, description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    type: Optional[TaskType] = Field(None, description="Type of the task")
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


# Resolve forward references
ScopeTask.model_rebuild()
MCPScopeTask.model_rebuild()


# --- Functions from mcp_models.py ---

def get_mode_instructions(mode: ScopeContextMode) -> str:
    """Generate instructions based on the scope context mode."""
    if mode == ScopeContextMode.ExecuteSubtasks:
        return f"Execute subtasks. On starting set their state in \"{TaskStatus.IN_PROGRESS}\" state and \"{TaskStatus.DONE}\" when finished and tested."
    elif mode == ScopeContextMode.FinalizeMasterTask:
        return f"All subtasks are completed. Review and finalize results of the implementation and move master task to \"{TaskStatus.DONE}\" state."
    return ""


def get_task_instruction(status: TaskStatus, type: TaskType, mode: ScopeContextMode, is_in_focus: bool) -> Tuple[str, str]:
    """Provides context and instructions for a task based on its state and the execution mode."""
    # --- Repetitive String Constants for Instructions and Notes ---
    NOTE_IRRELEVANT_TASK = "This task provided for information and context awareness. "

    INST_START_CODING = "Implement the required code changes for this task. "
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
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): ("", INST_START_CODING),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.ExecuteSubtasks): ("", INST_CONTINUE_CODING),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): ("", INST_START_REVIEW),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.ExecuteSubtasks): ("", INST_START_REVIEW + INST_CONTINUE_REVIEW),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): ("", INST_START_TESTING),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.ExecuteSubtasks): ("", INST_CONTINUE_TESTING),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): ("", INST_PROVIDE_INPUT),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.ExecuteSubtasks): ("", INST_CONTINUE_FOR_INPUT),

        # --- Mode: FinalizeMasterTask ---
        (TaskStatus.NOT_STARTED, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.CODE, ScopeContextMode.FinalizeMasterTask): ("", INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.REVIEW, ScopeContextMode.FinalizeMasterTask): ("", INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("", INST_FINALIZE_MASTER_TASK),
        (TaskStatus.IN_PROGRESS, TaskType.TEST, ScopeContextMode.FinalizeMasterTask): ("", INST_CONTINUE_FINALIZE_MASTER_TASK),
        (TaskStatus.NOT_STARTED, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", INST_PROVIDE_INPUT),
        (TaskStatus.IN_PROGRESS, TaskType.INPUT, ScopeContextMode.FinalizeMasterTask): ("", INST_CONTINUE_FOR_INPUT),
    }

    if not is_in_focus:
        return (NOTE_IRRELEVANT_TASK, "")

    if status == TaskStatus.DONE:
        return (NOTE_IRRELEVANT_TASK, INST_TASK_DONE)

    if status == TaskStatus.BLOCKED:
        return ("", INST_TASK_BLOCKED)

    key = (status, type, mode)
    return in_focus_instruction_map.get(key, ("", ""))


def create_mcp_task_from_scope_task(task: ScopeTask) -> MCPScopeTask:
    """Create an MCPScopeTask from a ScopeTask."""
    # Create the basic task state
    task_state = MCPScopeTask(
        designator=task.task_designator,
        name=task.name,
        description=task.description,
        status=task.status,
        type=task.type,
        requirements=[req.requirement_designator for req in task.requirements if req.requirement_designator],
        files=[file.file_path for file in task.files],
        subtasks=[]  # Will be filled later
    )
    return task_state


def set_context_info_and_notes(mcp_task: MCPScopeTask, scope_context: ScopeContext) -> None:
    """Set context info and notes for a task and its subtasks."""
    focus_tasks_designators = {td for td in scope_context.focus_tasks}

    def _set_context_info(_mcp_task: MCPScopeTask) -> None:
        _mcp_task.context_note, _mcp_task.instructions = get_task_instruction(
            _mcp_task.status, _mcp_task.type, scope_context.mode, _mcp_task.designator in focus_tasks_designators
        )

    def traverse_tasks(_mcp_task: MCPScopeTask) -> None:
        _set_context_info(_mcp_task)
        for subtask in _mcp_task.subtasks:
            traverse_tasks(subtask)

    traverse_tasks(mcp_task)


def convert_scope_context_to_mcp_response(scope_context: ScopeContext, base_path: Optional[str] = None) -> MCPScopeResponse:
    """Convert a ScopeContext to an MCPScopeResponse."""
    # Process all tasks recursively to build the task tree
    task_map = {}  # Map of designator to MCPScopeTask

    def process_scope_task(task: ScopeTask) -> MCPScopeTask:
        # Create MCPScopeTask from ScopeTask using the helper function
        mcp_task = create_mcp_task_from_scope_task(task)

        task_map[task.task_designator] = mcp_task

        for subtask in task.subtasks:
            subtask_state = process_scope_task(subtask)
            mcp_task.subtasks.append(subtask_state)

        return mcp_task

    # Process all top-level tasks
    top_level_tasks = []
    for task in scope_context.tasks:
        top_level_task = process_scope_task(task)
        set_context_info_and_notes(top_level_task, scope_context)
        top_level_tasks.append(top_level_task)

    response = MCPScopeResponse(
        progress_context=f"You are executing tasks scope by scope",
        instructions=get_mode_instructions(scope_context.mode),
        tasks=top_level_tasks
    )

    return response


def process_and_print_scope_context(scope_context: ScopeContext, case_name: str) -> None:
    """
    Process a ScopeContext through convert_scope_context_to_mcp_response and print the result.

    Args:
        scope_context: The ScopeContext to process
        case_name: A name for this case to identify it in the output
    """
    print(f"\n\n{'=' * 80}")
    print(f"CASE: {case_name}")
    print(f"{'=' * 80}")

    # Convert to MCP response
    response = convert_scope_context_to_mcp_response(scope_context)

    # Print the response as JSON
    print(json.dumps(response.model_dump(), indent=2))


def generate_basic_scope_context() -> ScopeContext:
    """Generate a basic ScopeContext with a single task."""
    task = ScopeTask(
        task_designator="TASK-1",
        name="Test Task",
        description="A test task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE,
        requirements=[
            RequirementReference(requirement_designator="REQ-1")
        ],
        files=[
            FileReference(file_path="/path/to/file.py")
        ]
    )

    return ScopeContext(
        tasks=[task],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1"]
    )


def generate_task_hierarchy_scope_context() -> ScopeContext:
    """Generate a ScopeContext with a task hierarchy."""
    subtask1 = ScopeTask(
        task_designator="TASK-1.1",
        name="Subtask 1",
        description="A subtask",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE
    )

    subtask2 = ScopeTask(
        task_designator="TASK-1.2",
        name="Subtask 2",
        description="Another subtask",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.TEST
    )

    parent_task = ScopeTask(
        task_designator="TASK-1",
        name="Parent Task",
        description="A parent task",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE,
        subtasks=[subtask1, subtask2]
    )

    return ScopeContext(
        tasks=[parent_task],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1.1", "TASK-1.2"]
    )


def generate_finalize_master_task_scope_context() -> ScopeContext:
    """Generate a ScopeContext with FinalizeMasterTask mode."""
    task = ScopeTask(
        task_designator="TASK-1",
        name="Test Task",
        description="A test task",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE
    )

    return ScopeContext(
        tasks=[task],
        project_id="PROJECT-1",
        mode=ScopeContextMode.FinalizeMasterTask,
        focus_tasks=["TASK-1"]
    )


def generate_focus_tasks_scope_context() -> ScopeContext:
    """Generate a ScopeContext with multiple tasks but only one in focus."""
    task1 = ScopeTask(
        task_designator="TASK-1",
        name="Task 1",
        description="First task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE
    )

    task2 = ScopeTask(
        task_designator="TASK-2",
        name="Task 2",
        description="Second task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE
    )

    return ScopeContext(
        tasks=[task1, task2],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1"]  # Only TASK-1 is in focus
    )


def generate_task_status_scope_context() -> ScopeContext:
    """Generate a ScopeContext with tasks of different statuses."""
    not_started_task = ScopeTask(
        task_designator="TASK-1",
        name="Not Started Task",
        description="A task not started",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE
    )

    in_progress_task = ScopeTask(
        task_designator="TASK-2",
        name="In Progress Task",
        description="A task in progress",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE
    )

    done_task = ScopeTask(
        task_designator="TASK-3",
        name="Done Task",
        description="A completed task",
        status=TaskStatus.DONE,
        type=TaskType.CODE
    )

    blocked_task = ScopeTask(
        task_designator="TASK-4",
        name="Blocked Task",
        description="A blocked task",
        status=TaskStatus.BLOCKED,
        type=TaskType.CODE
    )

    return ScopeContext(
        tasks=[not_started_task, in_progress_task, done_task, blocked_task],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1", "TASK-2", "TASK-3", "TASK-4"]
    )


def generate_task_type_scope_context() -> ScopeContext:
    """Generate a ScopeContext with tasks of different types."""
    code_task = ScopeTask(
        task_designator="TASK-1",
        name="Code Task",
        description="A coding task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE
    )

    review_task = ScopeTask(
        task_designator="TASK-2",
        name="Review Task",
        description="A review task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.REVIEW
    )

    test_task = ScopeTask(
        task_designator="TASK-3",
        name="Test Task",
        description="A testing task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.TEST
    )

    input_task = ScopeTask(
        task_designator="TASK-4",
        name="Input Task",
        description="An input task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.INPUT
    )

    return ScopeContext(
        tasks=[code_task, review_task, test_task, input_task],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1", "TASK-2", "TASK-3", "TASK-4"]
    )


def generate_complex_hierarchy_scope_context() -> ScopeContext:
    """Generate a complex ScopeContext with a deep task hierarchy and mixed statuses."""
    grandchild1 = ScopeTask(
        task_designator="TASK-1.1.1",
        name="Grandchild 1",
        description="A grandchild task",
        status=TaskStatus.DONE,
        type=TaskType.CODE
    )

    grandchild2 = ScopeTask(
        task_designator="TASK-1.1.2",
        name="Grandchild 2",
        description="Another grandchild task",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.TEST
    )

    child1 = ScopeTask(
        task_designator="TASK-1.1",
        name="Child 1",
        description="A child task",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE,
        subtasks=[grandchild1, grandchild2]
    )

    child2 = ScopeTask(
        task_designator="TASK-1.2",
        name="Child 2",
        description="Another child task",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.REVIEW
    )

    parent = ScopeTask(
        task_designator="TASK-1",
        name="Parent Task",
        description="A parent task",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE,
        subtasks=[child1, child2]
    )

    return ScopeContext(
        tasks=[parent],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-1.1.2", "TASK-1.2"]  # Focus on specific tasks
    )


def generate_empty_scope_context() -> ScopeContext:
    """Generate an empty ScopeContext."""
    return ScopeContext(
        tasks=[],
        project_id="PROJECT-1",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=[]
    )


def main():
    """Main function to generate and process all scope contexts."""
    # Define all the scope context generators
    scope_generators = {
        "Basic Scope Context": generate_basic_scope_context,
        "Task Hierarchy Scope Context": generate_task_hierarchy_scope_context,
        "Finalize Master Task Scope Context": generate_finalize_master_task_scope_context,
        "Focus Tasks Scope Context": generate_focus_tasks_scope_context,
        "Task Status Scope Context": generate_task_status_scope_context,
        "Task Type Scope Context": generate_task_type_scope_context,
        "Complex Hierarchy Scope Context": generate_complex_hierarchy_scope_context,
        "Empty Scope Context": generate_empty_scope_context
    }

    # Generate and process each scope context
    for name, generator in scope_generators.items():
        scope_context = generator()
        process_and_print_scope_context(scope_context, name)


if __name__ == "__main__":
    main()
