from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from ..api.api_models import AccountInfo
from ..services.mcp_config_service import MCPConfigStatus


@dataclass(kw_only=True)
class IntegrationStatus:
    """Data class representing current integration status."""

    config_loaded: bool = False
    config_path: Optional[Path] = None
    config_summary: Optional[Dict[str, Any]] = None
    
    # Network connectivity status
    network_connected: bool = False
    network_response_time: Optional[float] = None
    network_error: Optional[str] = None
    
    # API connectivity status
    api_connected: bool = False
    account_info: Optional[AccountInfo] = None
    
    # MCP integration status
    mcp_status: MCPConfigStatus = MCPConfigStatus.NOT_FOUND
    mcp_config_path: Optional[Path] = None
    
    # Overall integration status
    integration_ready: bool = False
    status_message: str = ""
