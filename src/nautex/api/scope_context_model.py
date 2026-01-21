from typing import List, Optional
from pydantic import BaseModel, Field
import os
from enum import Enum


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
    EXPLORE = "Explore"


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
    description: str = Field(None, description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    type: TaskType = Field(..., description="Type of the task (Code, Review, Test, Input, Explore)")
    subtasks: List["ScopeTask"] = Field(default_factory=list, description="List of subtasks")

    # parent_task: Optional[TaskReference] = Field(None, description="Reference to parent task")

    requirements: List[RequirementReference] = Field(default_factory=list, description="List of requirement references")
    files: List[FileReference] = Field(default_factory=list, description="List of file references")


class ScopeContext(BaseModel):
    """Root model for scope context representing a tasks tree fragment."""
    tasks: List[ScopeTask] = Field(default_factory=list, description="List of tasks in the scope")
    project_id: Optional[str] = Field(None, description="Project identifier")
    mode: ScopeContextMode = Field(..., description="Current state of the scope context")
    focus_tasks: List[str] = Field(default_factory=list, description="List of task designators to focus on")

    def find_task_by_designator(self, designator: str) -> Optional[ScopeTask]:
        """
        Find a task by its designator.

        Args:
            designator: The task designator to search for

        Returns:
            The task with the specified designator, or None if not found
        """
        def _find_task_recursive(task: ScopeTask) -> Optional[ScopeTask]:
            if task.task_designator == designator:
                return task

            for subtask in task.subtasks:
                found = _find_task_recursive(subtask)
                if found:
                    return found

            return None

        for task in self.tasks:
            found = _find_task_recursive(task)
            if found:
                return found

        return None

    def is_done(self):
        all_tasks = []

        def _traverse_tasks(task):
            all_tasks.append(task)
            for subtask in task.subtasks:
                _traverse_tasks(subtask)

        one = len(self.tasks) == 0
        two = all([t.status == TaskStatus.DONE for t in all_tasks])

        return one or two

    def print_scope_tree(self) -> None:
        """
        Print the scope tree structure to the console.
        This is a helper function to visualize the task hierarchy.
        """
        if not self.tasks:
            print("Scope is empty or all tasks are done.")
            return

        for task in self.tasks:
            self._print_task_tree(task)

    def _print_task_tree(self, task: ScopeTask, prefix: str = "", is_last: bool = True) -> None:
        """
        Helper function to print a task and its subtasks in a tree structure.

        Args:
            task: The task to print
            prefix: Current line prefix for formatting
            is_last: Whether this is the last item in its branch
        """
        # Print current task with appropriate tree characters
        status_info = f"[{task.status.value}]"
        print(prefix + ("└── " if is_last else "├── ") + f"{task.task_designator} - {task.name} {status_info}")

        # Prepare prefix for children
        child_prefix = prefix + ("    " if is_last else "│   ")

        # Print all subtasks
        if task.subtasks:
            for i, subtask in enumerate(task.subtasks):
                self._print_task_tree(subtask, child_prefix, i == len(task.subtasks) - 1)

    def render_as_plain_text(self, base_path: Optional[str] = None) -> str:
        """
        Render the scope as plain text.

        Args:
            base_path: Optional base path for rendering relative file paths.
                      If not provided, file paths will be rendered as is.

        Returns:
            A string representation of the scope.
        """
        lines = []

        if self.project_id:
            lines.append(f"Project: {self.project_id}")
            lines.append("")

        for task in self.tasks:
            lines.extend(self._render_task(task, 0, base_path))

        return "\n".join(lines)

    def _render_task(self, task: ScopeTask, indent_level: int, base_path: Optional[str] = None) -> List[str]:
        """
        Render a task and its subtasks as plain text.

        Args:
            task: The task to render.
            indent_level: The current indentation level.
            base_path: Optional base path for rendering relative file paths.

        Returns:
            A list of strings representing the task.
        """
        indent = "  " * indent_level
        lines = []

        # Render task header
        task_header = f"{indent}Task: {task.task_designator}"
        if task.name:
            task_header += f" - {task.name}"
        lines.append(task_header)

        # Render task status
        lines.append(f"{indent}  Status: {task.status.value}")

        # Render task type
        lines.append(f"{indent}  Type: {task.type.value}")

        # Render task description if available
        if task.description:
            lines.append(f"{indent}  Description: {task.description}")

        # Render requirements
        if task.requirements:
            lines.append(f"{indent}  Requirements:")
            for req in task.requirements:
                lines.append(f"{indent}    - {req.requirement_designator}")

        # Render files
        if task.files:
            lines.append(f"{indent}  Files:")
            for file in task.files:
                file_path = file.file_path
                if base_path and os.path.isabs(file_path):
                    try:
                        file_path = os.path.relpath(file_path, base_path)
                    except ValueError:
                        # If paths are on different drives, keep the original path
                        pass
                lines.append(f"{indent}    - {file_path}")

        # Parent task reference is commented out in the model definition
        # Uncomment the following if parent_task is added to the model
        # if hasattr(task, 'parent_task') and task.parent_task:
        #     lines.append(f"{indent}  Parent: {task.parent_task.task_designator}")

        # Add a blank line after task details
        lines.append("")

        # Render subtasks
        for subtask in task.subtasks:
            lines.extend(self._render_task(subtask, indent_level + 1, base_path))

        return lines

# Resolve forward reference for ScopeTask.subtasks
ScopeTask.model_rebuild()
