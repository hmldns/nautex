"""Markdown/YAML format response descriptions for MCP workflow prompts."""

from ..api.scope_context_model import TaskStatus, TaskType
from .consts import CMD_NEXT_SCOPE, CMD_TASKS_UPDATE, DIR_NAUTEX_DOCS
from .response_format_comments import FieldComments as FC


def _ym(comment: str, indent: str = "") -> str:
    """Format comment for YAML (# style), handling multiline."""
    lines = comment.split('\n')
    return '\n'.join(f"{indent}# {line}" for line in lines)


NEXT_SCOPE_RESPONSE_DESCRIPTION = f"""### Example of the `{CMD_NEXT_SCOPE}` response data structure:

Response is formatted as Markdown with a YAML code block. Field comments explain the structure.

```yaml
progress_context: |
  {FC.PROGRESS_CONTEXT}...
instructions: |
  {FC.INSTRUCTIONS}...

{_ym(FC.DOCUMENTS_PATHS)}
documents_paths:
  PRD: {DIR_NAUTEX_DOCS}/PRD.md
  TRD: {DIR_NAUTEX_DOCS}/TRD.md
  FILE: {DIR_NAUTEX_DOCS}/FILE.md  # {FC.FILE_DOCUMENT}

{_ym(FC.DESIGNATORS)}

{_ym(FC.TASKS_LIST)}
tasks:
  # {FC.MASTER_TASK}
  - designator: T-1
    name: Implement User Authentication
    workflow_info:  # {FC.WORKFLOW_INFO}
      in_focus: true  # {FC.WORKFLOW_INFO_IN_FOCUS}
    description: Create the backend infrastructure for user registration and login.
    status: {TaskStatus.NOT_STARTED.value}
    type: {TaskType.CODE.value}
    requirements:  # {FC.REQUIREMENTS}
      - PRD-201
    files:  # {FC.FILES}
      - src/services/auth_service.py
      - src/api/auth_routes.py

    # {FC.SUBTASKS_LIST}
    subtasks:
      # {FC.SUBTASK_1}
      - designator: T-2
        name: Create Authentication Service
        workflow_info:
          in_focus: true
          context_note: ...  # {FC.WORKFLOW_INFO_CONTEXT_NOTE}
          instructions: ...  # {FC.WORKFLOW_INFO_INSTRUCTIONS}
        description: |
          Implement the business logic for user authentication,
          including password hashing and token generation.
        status: {TaskStatus.NOT_STARTED.value}
        type: {TaskType.CODE.value}
        requirements:  # {FC.REQUIREMENTS_TRD}
          - TRD-55
          - TRD-56
        files:
          - src/services/auth_service.py

      # {FC.SUBTASK_2}
      - designator: T-3
        name: Create Authentication API Endpoint
        workflow_info:
          in_focus: false
        description: Create a public API endpoint for user login.
        status: {TaskStatus.NOT_STARTED.value}
        type: {TaskType.CODE.value}
        # {FC.OMITTED}

      # {FC.SUBTASK_3}
      - designator: T-4
        name: Test Authentication Implementation
        workflow_info:
          in_focus: false
        description: |
          Write and execute tests to verify the implemented authentication
          service and endpoints work correctly.
        status: {TaskStatus.NOT_STARTED.value}
        type: {TaskType.TEST.value}
        # {FC.OMITTED}

      # {FC.SUBTASK_4}
      - designator: T-5
        name: "{TaskType.REVIEW.value} Authentication Flow"
        workflow_info:
          in_focus: false
        description: |
          Ask the user to review the implemented authentication endpoints
          to ensure they meet expectations.
        status: {TaskStatus.NOT_STARTED.value}
        # {FC.OMITTED}
```"""


TASKS_UPDATE_RESPONSE_DESCRIPTION = f"""### Example `{CMD_TASKS_UPDATE}` Response (Markdown/YAML):
```yaml
success: true
message: Tasks updated successfully
```"""
