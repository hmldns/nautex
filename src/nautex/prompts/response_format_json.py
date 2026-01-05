"""JSON format response descriptions for MCP workflow prompts."""

from ..api.scope_context_model import TaskStatus, TaskType
from .consts import CMD_NEXT_SCOPE, CMD_TASKS_UPDATE, DIR_NAUTEX_DOCS
from .response_format_comments import FieldComments as FC


def _js(comment: str) -> str:
    """Format comment for JSON (// style), handling multiline."""
    lines = comment.split('\n')
    if len(lines) == 1:
        return f"// {comment}"
    return '\n    '.join(f"// {line}" for line in lines)


NEXT_SCOPE_RESPONSE_DESCRIPTION = f"""### Example of the `{CMD_NEXT_SCOPE}` response data structure:

JSON fields are just examples, "//" escaped lines are explanations.

```
{{{{
  "success": true,
  "data": {{{{
    "progress_context": "...", {_js(FC.PROGRESS_CONTEXT)}
    "instructions": "...", {_js(FC.INSTRUCTIONS)}

    {_js(FC.DOCUMENTS_PATHS)}
    "documents_paths": {{{{
      "PRD": "{DIR_NAUTEX_DOCS}/PRD.md",
      "TRD": "{DIR_NAUTEX_DOCS}/TRD.md",
      "FILE": "{DIR_NAUTEX_DOCS}/FILE.md"  // {FC.FILE_DOCUMENT}
    }}}},

    {_js(FC.DESIGNATORS)}

    {_js(FC.TASKS_LIST)}
    "tasks": [
      {{{{
        {_js(FC.MASTER_TASK)}
        "designator": "T-1",
        "name": "Implement User Authentication",
        {_js(FC.WORKFLOW_INFO)}
        "workflow_info": {{{{
          "in_focus": true  // {FC.WORKFLOW_INFO_IN_FOCUS}
        }}}},
        "description": "Create the backend infrastructure for user registration and login.",
        "status": "{TaskStatus.NOT_STARTED.value}",
        "type": "{TaskType.CODE.value}",
        "requirements": ["PRD-201"], // {FC.REQUIREMENTS}
        "files": ["src/services/auth_service.py", "src/api/auth_routes.py"], // {FC.FILES}

        {_js(FC.SUBTASKS_LIST)}
        "subtasks": [
          {{{{
            {_js(FC.SUBTASK_1)}
            "designator": "T-2",
            "name": "Create Authentication Service",
            "workflow_info": {{{{
              "in_focus": true,
              "context_note": "...",  // {FC.WORKFLOW_INFO_CONTEXT_NOTE}
              "instructions": "..."   // {FC.WORKFLOW_INFO_INSTRUCTIONS}
            }}}},
            "description": "Implement the business logic for user authentication, including password hashing and token generation.",
            "status": "{TaskStatus.NOT_STARTED.value}",
            "type": "{TaskType.CODE.value}",
            "requirements": ["TRD-55", "TRD-56"], // {FC.REQUIREMENTS_TRD}
            "files": ["src/services/auth_service.py"]
          }}}},
          {{{{
            {_js(FC.SUBTASK_2)}
            "designator": "T-3",
            "name": "Create Authentication API Endpoint",
            "workflow_info": {{{{"in_focus": false}}}},
            "description": "Create a public API endpoint for user login.",
            "status": "{TaskStatus.NOT_STARTED.value}",
            "type": "{TaskType.CODE.value}"
            // {FC.OMITTED}
          }}}},
          {{{{
            {_js(FC.SUBTASK_3)}
            "designator": "T-4",
            "name": "Test Authentication Implementation",
            "workflow_info": {{{{"in_focus": false}}}},
            "description": "Write and execute tests to verify the implemented authentication service and endpoints work correctly.",
            "status": "{TaskStatus.NOT_STARTED.value}",
            "type": "{TaskType.TEST.value}"
            // {FC.OMITTED}
          }}}},
          {{{{
            {_js(FC.SUBTASK_4)}
            "designator": "T-5",
            "name": "{TaskType.REVIEW.value} Authentication Flow",
            "workflow_info": {{{{"in_focus": false}}}},
            "description": "Ask the user to review the implemented authentication endpoints to ensure they meet expectations.",
            "status": "{TaskStatus.NOT_STARTED.value}"
            // {FC.OMITTED}
          }}}}
        ]
      }}}}
    ]
  }}}}
}}}}
```"""


TASKS_UPDATE_RESPONSE_DESCRIPTION = f"""### Example `{CMD_TASKS_UPDATE}` Response:
```json
{{{{
  "success": true,
  "message": "Tasks updated successfully"
}}}}
```"""
