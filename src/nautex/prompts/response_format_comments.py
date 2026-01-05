"""Common field descriptions for MCP response format documentation."""


class FieldComments:
    """Reusable field comments/descriptions for response format documentation."""

    # Top-level fields
    PROGRESS_CONTEXT = "A high-level explanation of what is going on"
    INSTRUCTIONS = "General, high-level instructions for the agent that apply to the entire scope of tasks"

    # Documents paths
    DOCUMENTS_PATHS = (
        "A dictionary mapping document designators to path relative to the project root.\n"
        "These documents (e.g., Product Requirements Document, Technical Requirements Document) contain\n"
        "the detailed specifications referenced in the tasks. The agent must read these files to\n"
        "fully understand the requirements. Search by full designators would work."
    )
    FILE_DOCUMENT = "refer to this document for managing expected file structure"

    # Designators
    DESIGNATORS = (
        "Designators are composed via 2 parts: DOC_DESIGNATOR-ITEM_DESIGNATOR\n"
        "DOC_DESIGNATOR - is string, ITEM_DESIGNATOR - is number of statement inside the document."
    )

    # Tasks
    TASKS_LIST = (
        "The core of the response: a list of tasks that the agent needs to execute.\n"
        "Tasks can be nested to represent a hierarchical work breakdown structure to represent the context of the process."
    )
    MASTER_TASK = "The master task that groups several subtasks related to authentication."
    REQUIREMENTS = "reference to the specific requirements in PRD file (document)"
    REQUIREMENTS_TRD = "references to the specific requirements in TRD or PRD requirements files - documents"
    FILES = "reference to files related to the task and expected to be updated / created; referenced directory will have trailing \"/\", e.g. src/services/"

    # Subtasks
    SUBTASKS_LIST = "A list of subtasks that break down the parent task into smaller, manageable steps."
    SUBTASK_1 = "The first subtask: creating a service to handle authentication logic."
    SUBTASK_2 = "The second subtask: exposing the authentication logic via an API endpoint."
    SUBTASK_3 = "Third subtask: writing and executing tests for the authentication service and endpoints."
    SUBTASK_4 = "A standalone task for user review after the coding and testing tasks are complete."

    # Task workflow_info fields
    WORKFLOW_INFO = (
        "Workflow orchestration metadata - determines how the agent should handle this task. "
        "in_focus signals whether to execute this task now or treat as context only."
    )
    WORKFLOW_INFO_IN_FOCUS = "true = execute this task; false = provided for context awareness only"
    WORKFLOW_INFO_CONTEXT_NOTE = "explains task's role in the current workflow state"
    WORKFLOW_INFO_INSTRUCTIONS = "actionable directives for the agent based on task type and status"
    OMITTED = "other fields omitted for clarity"
