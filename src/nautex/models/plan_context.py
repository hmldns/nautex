"""Plan Context dataclass for aggregated plan status."""

from dataclasses import dataclass
from typing import Optional, Any
from pathlib import Path

from ..utils.mcp_utils import MCPConfigStatus
from ..api.api_models import Task


@dataclass
class PlanContext:
    """Aggregated context for current plan status.

    This model is used by PlanContextService to provide a comprehensive
    view of the current CLI state, including configuration, API connectivity,
    and next available task.
    """
    config_loaded: bool
    mcp_status: MCPConfigStatus
    api_connected: bool
    advised_action: str
    timestamp: str
    
    # Optional fields
    config_path: Optional[Path] = None
    mcp_config_path: Optional[Path] = None
    api_response_time: Optional[float] = None
    next_task: Optional[Task] = None
    
    # Using Any for config to avoid circular import with NautexConfig
    config_summary: Optional[Any] = None