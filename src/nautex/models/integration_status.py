from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from src.nautex.models.api_models import AccountInfo
from src.nautex.services.mcp_config_service import MCPConfigStatus


@dataclass(kw_only=True)
class IntegrationStatus:
    """Data class representing current integration status."""

    config_loaded: bool = False
    config_path: Optional[Path] = None
    config_summary: Optional[Dict[str, Any]] = None
    api_connected: bool = False
    api_response_time: Optional[float] = None
    account_info: Optional[AccountInfo] = None
    mcp_status: MCPConfigStatus = MCPConfigStatus.NOT_FOUND
    mcp_config_path: Optional[Path] = None
    integration_ready: bool = False
    status_message: str = ""
