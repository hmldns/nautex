"""Common workflow prompt for MCP integration."""

from ..api.scope_context_model import TaskStatus, TaskType
from ..models.config import MCPOutputFormat
from .consts import (
    CMD_STATUS,
    CMD_NEXT_SCOPE,
    CMD_TASKS_UPDATE,
    DIR_NAUTEX,
    DIR_NAUTEX_DOCS,
)
from .terminology import Terminology as Terms


# Format-agnostic parts of the workflow prompt
_WORKFLOW_INTRO = f"""
# General background and workflow

This document outlines the workflow for an AI {Terms.AGENT} interacting with the {Terms.PRODUCT} AI platform via the {Terms.PROTOCOL}.
The primary goal is to systematically pull tasks from {Terms.PRODUCT}, execute them according to the provided scope and requirements, and report progress back to the platform.

{Terms.PRODUCT} acts as a project management system, breaking down development into specific, actionable tasks. The agent's role is to act as the software developer, implementing these tasks.
The agent must strictly adhere to the scope defined in each task, including operating only on the specified files in task and fulfilling the given requirements.

## Workflow Goal

The agent's goal is to implement a plan provided by {Terms.PRODUCT}. This is achieved through a cyclical process of fetching tasks, implementing them, and updating their status.

The core workflow is as follows:
1.  **Fetch Scope:** Use the `{CMD_NEXT_SCOPE}` command to retrieve the current set of active tasks from {Terms.PRODUCT}.
2.  **Acknowledge Tasks:** After receiving tasks, update their status to `{TaskStatus.IN_PROGRESS.value}` using the `{CMD_TASKS_UPDATE}` for those tasks that are marked as "in_focus" AND are going to be actionable withing one coherent chunk of {Terms.AGENT} work.
    This signals to the platform that you have started working on them and it is helpful for you for tasks handover between chat sessions.
3.  **Compose relevant context:** The {Terms.AGENT} must compose the context from the documents referenced in the tasks and understand their context and goals.
    - Reading full requirements document is always preferable.
    - Alternatively search by full designators would work, make sure you pull the full records content from adjacent lines.
    - Always resolve other requirements references by other requirements.
    - When referenced document element is section, whole section should be loaded into context.
    - Navigate by hierarchy: Major sections start with ## [TRD-X], subsections with ### [TRD-XXX], use document outline or search these patterns to jump between topics, always absorb whole relevant sections.

4.  **Implement Tasks:** Analyze the task details (description, type, requirements, associated files) and perform the necessary actions, such as writing or modifying code.
5.  **Complete Tasks:** Once a task is fully implemented, update its status to `{TaskStatus.DONE.value}` using the `{CMD_TASKS_UPDATE}` command.
6.  **Repeat:** Continue this cycle until `{CMD_NEXT_SCOPE}` returns no new tasks.

CRITICAL: NEVER EDIT FILES IN `{DIR_NAUTEX}` directory

# Commands

## `{CMD_STATUS}`

Whenever you asked to get {Terms.PRODUCT.lower()} status, you should call this command; it is ok to call it before other commands to check that integration works correctly.

## `{CMD_NEXT_SCOPE}`

This is the primary command to fetch the next set of tasks from the {Terms.PRODUCT} platform. When called, it returns an object containing the tasks that the agent should work on.

- **Usage:** Call this command at the beginning of your workflow and after you have completed all in focus tasks from the previous scope.
- **Response:** The response includes general instructions, paths to relevant documents, and a list of tasks objects.

"""

_NEXT_SCOPE_NOTES = f"""
Response object `{CMD_NEXT_SCOPE}` has inline instructions for scope and tasks.
Each task has a `workflow_info` object containing:
- `in_focus`: true means execute this task; false means it's provided for context only
- `context_note`: explains the task's role in current workflow state (if present)
- `instructions`: actionable directives based on task type and status

Focus tasks are those with `workflow_info.in_focus` set to true. Status changes are only allowed for in-focus tasks.
Tasks not in focus are given for context for progress handover and parent scope understanding (e.g. some chunk of work within the scope).

### The `full` Parameter

The `{CMD_NEXT_SCOPE}` command accepts an optional `full` boolean parameter (defaults to `true`):

**When to use `full=true` (default):**
- Starting a new session and need to orient yourself in the project
- After completing a major milestone and need to see what's next across the whole plan
- When stuck or confused about overall progress and relationships between tasks
- When the user asks about overall project status or remaining work
- When tasks structure was re-arranged and you detect change in the scope, user may tell that too.

**When to use `full=false`:**
- During normal task execution workflow, after pauses in the execution cycle
- For quick info refreshing and in project navigation on minor in phase / milestone tasks status change

CRITICAL: `{CMD_TASKS_UPDATE}` command also shows next scope with `full=false`, compact version of `{CMD_NEXT_SCOPE}` for saving turns, so, no need to bundle `{CMD_TASKS_UPDATE}` and `{CMD_NEXT_SCOPE}` commands together. 

## `{CMD_TASKS_UPDATE}`

This command updates task status. Call it whenever a task's status changes (e.g., from `{TaskStatus.NOT_STARTED.value}` to `{TaskStatus.IN_PROGRESS.value}`, or from `{TaskStatus.IN_PROGRESS.value}` to `{TaskStatus.DONE.value}`).

-   **Usage:** Send a list of operations with task designators and new statuses.
-   **Response:** Automatically includes the next focus tasks (compact next scope) after any successful update, so you can see what's next without a separate `{CMD_NEXT_SCOPE}` call.
-   **Compact scope format:** Contains only focus tasks (those with `workflow_info.in_focus: true`) as a flat list, without `progress_context`, `instructions`, or `documents_paths` fields. Use `{CMD_NEXT_SCOPE}` with `full=true` when you need full context.
-   **Important:** Timely updates are crucial for the workflow to track progress accurately.


### Example `{CMD_TASKS_UPDATE}` Payload:
```json
{{
  "operations": [
    {{
      "task_designator": "T-1",
      "updated_status": "{TaskStatus.IN_PROGRESS.value}",
      "new_note": "Starting work on the main authentication task. Subtasks will be addressed sequentially."
    }},
    {{
      "task_designator": "T-2",
      "updated_status": "{TaskStatus.DONE.value}",
      "new_note": "The 'AuthService' class has been implemented in 'src/services/auth_service.py' as per the requirements. Password hashing and JWT generation are complete."
    }},
    {{
      "task_designator": "T-3",
      "updated_status": "{TaskStatus.BLOCKED.value}",
      "new_note": "Blocked: Waiting for clarification on the expected JSON response format for the '/login' endpoint. I will proceed with other tasks until this is resolved."
    }},
    {{
      "task_designator": "T-4",
      "new_note": "User review is the next step after the login endpoint is fully implemented and unblocked."
    }}
  ]
}}

```

"""

_WORKFLOW_OUTRO = f"""
# Task Workflow and Statuses

Tasks progress through a simple lifecycle, managed by the agent. The valid statuses are:

1.  **{TaskStatus.NOT_STARTED.value}**: The default initial state of a task.
2.  **{TaskStatus.IN_PROGRESS.value}**: Set this as soon as you start executing the task.
3.  **{TaskStatus.DONE.value}**: Set this once all work for the task is complete.
4.  **{TaskStatus.BLOCKED.value}**: Use when progress is blocked and a note explains why.

# Task Types

Each task object has a `type` that informs the agent about the nature of the work required. The valid types are:

-   **{TaskType.CODE.value}**: The primary task type. The agent is expected to write or modify application source code based on the provided `description` and `requirements`.
-   **{TaskType.REVIEW.value}**: This task requires user validation. The `description` will contain a script for the agent to follow, guiding it on what to show the user (e.g., code, application behavior, UI flow) and what specific feedback to ask for. This is a critical step for de-risking the project.
-   **{TaskType.TEST.value}**: This task involves writing or executing tests to verify that the code works as expected. The `description` will describe the test cases or strategy (e.g., "Write unit tests for the `calculate_total` function, covering positive, negative, and zero values."). Referenced requirements should be taken in account as sell.
-   **{TaskType.INPUT.value}**: This task requires the agent to gather specific information, often from the user. The `description` will detail what is needed (e.g., API keys, `.env` file settings, configuration data) and provide a script for how to ask the user for it.
-   **{TaskType.EXPLORE.value}**: This task requires the agent to explore existing codebase before implementation. The `description` will instruct the agent on what files/patterns to examine, what questions to answer about existing code, and how to present findings to the user comparing plan vision vs actual codebase state (gaps, contradictions, integration points). Propose solutions for gaps and make decisions with user before proceeding. Do not mark as 'Done' until the user explicitly confirms the exploration findings and decisions. Used when improving existing projects.

# Interaction Goals and Guiding Principles

-   **Consult Documents:** Tasks often reference requirements (e.g., `PRD-101`, `TRD-42`). These references point to items within documents provided in the `documents_paths` field of `{CMD_NEXT_SCOPE}` response.
     You **must** open these local markdown files to read the requirements and fully understand the task's context and goals. Documents are downloaded and stored locally in the directories provided.
-   **Obey the Scope:** The agent's primary directive is to work within the confines of the tasks provided by {Terms.PRODUCT}. Do not modify files or implement functionality not explicitly mentioned in the current task's scope.
-   **Follow Instructions:** The `workflow_info.instructions` field provides guidance according to the task type and status.
-   **Be Methodical:** Address reasonable number of tasks at a time. Complete the full workflow for a task (`{TaskStatus.IN_PROGRESS.value}` -> Implement -> `{TaskStatus.DONE.value}`) before moving to the next.
-   **Communicate Clearly:** Use the `{CMD_TASKS_UPDATE}` command to provide clear and immediate feedback on your progress. This is essential for the health of the project on the {Terms.PRODUCT} platform.
-   **Manage referenced files consistently:** Operate with files referenced by tasks, be aware that all paths are relative to the project root.

# Dealing with Errors

If `{CMD_NEXT_SCOPE}` returns an error, you must **stop the workflow immediately**. Do not proceed with any further tasks or commands.
For `{CMD_TASKS_UPDATE}` command, follow error message and adjust argument if relevant. If error is not arguments related, stop the workflow immediately as well.

Report the error to the user, providing any details from the error message.
This ensures that problems are addressed promptly and prevents the workflow from continuing in an inconsistent or unpredictable state. After reporting the error, wait for further instructions.
"""


def get_common_workflow_prompt(response_format: MCPOutputFormat) -> str:
    """Generate the common workflow prompt based on response format.

    Args:
        response_format: The MCP response format to use for examples

    Returns:
        The complete workflow prompt string with format-appropriate examples
    """
    if response_format == MCPOutputFormat.MD_YAML:
        from .response_format_md_yaml import (
            NEXT_SCOPE_RESPONSE_DESCRIPTION,
            TASKS_UPDATE_RESPONSE_DESCRIPTION,
        )
    else:
        from .response_format_json import (
            NEXT_SCOPE_RESPONSE_DESCRIPTION,
            TASKS_UPDATE_RESPONSE_DESCRIPTION,
        )

    return (
        _WORKFLOW_INTRO
        + NEXT_SCOPE_RESPONSE_DESCRIPTION
        + _NEXT_SCOPE_NOTES
        + TASKS_UPDATE_RESPONSE_DESCRIPTION
        + _WORKFLOW_OUTRO
    )
