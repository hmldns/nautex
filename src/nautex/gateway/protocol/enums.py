"""Protocol enumerations shared between utility and backend.

All enum values are derived from empirical ACP probe evidence
and the gateway service design.
"""

from __future__ import annotations

from enum import Enum


class SessionUpdateKind(str, Enum):
    """ACP session update types observed across all 8 agents.

    Discovered via probe --consolidate runs against real agents.
    """
    AGENT_MESSAGE = "agent_message_chunk"
    AGENT_THOUGHT = "agent_thought_chunk"
    TOOL_CALL = "tool_call"
    TOOL_CALL_UPDATE = "tool_call_update"
    AVAILABLE_COMMANDS = "available_commands_update"
    CURRENT_MODE = "current_mode_update"
    USAGE = "usage_update"
    CONFIG_OPTION = "config_option_update"
    SESSION_INFO = "session_info_update"
    TURN_STARTED = "turn_started"
    TURN_COMPLETE = "turn_complete"


class ToolCallStatus(str, Enum):
    """Tool call lifecycle status from ACP."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"


class ToolKind(str, Enum):
    """Tool execution kind from ACP."""
    EDIT = "edit"
    EXECUTE = "execute"
    READ = "read"
    SEARCH = "search"


class PermissionAction(str, Enum):
    """User decision on a permission request."""
    APPROVE = "approve"
    DENY = "deny"


class AgentLifecycleEvent(str, Enum):
    """Agent lifecycle event types."""
    STARTED = "started"
    EXITED = "exited"        # clean termination
    CRASHED = "crashed"      # abnormal termination


class NodeStatus(str, Enum):
    """Gateway node health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"
