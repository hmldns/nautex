"""Sample script to generate ScopeContext instances and convert them to MCP responses."""

import json


from src.nautex.api.scope_context_model import ScopeContextMode, ScopeContext, ScopeTask, TaskStatus, TaskType, \
    RequirementReference, FileReference
from src.nautex.models.mcp import convert_scope_context_to_mcp_response


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
    response = convert_scope_context_to_mcp_response(scope_context, {})

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
    # Create subtasks that are in DONE state
    subtask1 = ScopeTask(
        task_designator="TASK-1.1",
        name="Subtask 1",
        description="A completed subtask",
        status=TaskStatus.DONE,
        type=TaskType.CODE
    )

    subtask2 = ScopeTask(
        task_designator="TASK-1.2",
        name="Subtask 2",
        description="Another completed subtask",
        status=TaskStatus.DONE,
        type=TaskType.TEST
    )

    # Create the master task with subtasks in DONE state
    master_task = ScopeTask(
        task_designator="TASK-1",
        name="Master Task",
        description="A master task with completed subtasks",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.CODE,
        subtasks=[subtask1, subtask2]
    )

    return ScopeContext(
        tasks=[master_task],
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
