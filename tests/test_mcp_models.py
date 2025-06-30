"""Tests for the MCP models and conversion functions."""

import sys
import json
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the actual models and enums
from src.nautex.api.scope_context_model import (
    TaskStatus,
    TaskType,
    ScopeContextMode,
    Reference,
    RequirementReference,
    FileReference,
    ScopeTask,
    ScopeContext
)

from src.nautex.models.mcp_models import (
    convert_scope_context_to_mcp_response,
    MCPScopeTask,
    MCPScopeResponse
)


def create_test_scope_context():
    """Create a test ScopeContext instance for testing."""
    # Create a requirement reference
    req_ref = RequirementReference(
        root_id="doc1",
        item_id="item1",
        requirement_designator="REQ-45"
    )

    # Create a file reference
    file_ref = FileReference(
        root_id="doc1",
        item_id="item2",
        file_path="src/auth/login.py"
    )

    # Create a subtask
    subtask = ScopeTask(
        task_designator="TASK-124",
        name="Implement login endpoint",
        description="Create the login API endpoint",
        status=TaskStatus.NOT_STARTED,
        type=TaskType.CODE,
        requirements=[req_ref],
        files=[file_ref]
    )

    # Create a parent task
    parent_task = ScopeTask(
        task_designator="TASK-123",
        name="Implement user authentication",
        description="Create login and registration endpoints",
        status=TaskStatus.IN_PROGRESS,
        type=TaskType.REVIEW,
        subtasks=[subtask],
        requirements=[req_ref],
        files=[file_ref]
    )

    # Create the scope context
    scope_context = ScopeContext(
        tasks=[parent_task],
        project_id="PROJ-123",
        mode=ScopeContextMode.ExecuteSubtasks,
        focus_tasks=["TASK-123"]
    )

    return scope_context


def test_convert_scope_context_to_mcp_response():
    """Test the conversion from ScopeContext to MCPScopeResponse."""
    # Create a test scope context
    scope_context = create_test_scope_context()

    # Convert to MCP response
    mcp_response = convert_scope_context_to_mcp_response(scope_context)

    # Print the response as JSON for inspection
    print(json.dumps(mcp_response.model_dump(), indent=2))

    # Verify the conversion - adapted for new MCPScopeResponse structure
    # Check progress_context and instructions
    assert "ExecuteSubtasks" in mcp_response.progress_context
    assert "Execute subtasks in order" in mcp_response.instructions

    # Check tasks
    assert len(mcp_response.tasks) == 1
    parent_task = mcp_response.tasks[0]
    assert parent_task.designator == "TASK-123"
    assert parent_task.name == "Implement user authentication"
    assert parent_task.status == TaskStatus.IN_PROGRESS.value
    assert parent_task.requirements == ["REQ-45"]
    assert parent_task.files == ["src/auth/login.py"]
    assert "subtasks" in parent_task.instructions.lower()

    # Check subtasks
    assert len(parent_task.subtasks) == 1
    subtask = parent_task.subtasks[0]
    assert subtask.designator == "TASK-124"
    assert subtask.name == "Implement login endpoint"
    assert subtask.status == TaskStatus.NOT_STARTED.value
    assert subtask.requirements == ["REQ-45"]
    assert subtask.files == ["src/auth/login.py"]
    assert "not started" in subtask.instructions.lower()
    assert "Task type: Code" in subtask.context_note
    assert "Consider this task for your information" in subtask.context_note

    print("All tests passed!")


if __name__ == "__main__":
    test_convert_scope_context_to_mcp_response()