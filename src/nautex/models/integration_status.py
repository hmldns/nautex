from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from .config import NautexConfig
from ..api.api_models import AccountInfo
from ..services.mcp_config_service import MCPConfigStatus


@dataclass(kw_only=True)
class IntegrationStatus:
    """Data class representing current integration status."""

    @property
    def config_loaded(self):
        return bool(self.config)

    config: Optional[NautexConfig] = None

    # Network connectivity status
    network_connected: bool = False
    network_response_time: Optional[float] = None
    network_error: Optional[str] = None

    # API connectivity status
    api_connected: bool = False
    account_info: Optional[AccountInfo] = None

    @property
    def project_selected(self):
        return self.config and self.config.project_id

    @property
    def plan_selected(self):
        return self.config and self.config.plan_id

    # MCP integration status
    mcp_config_set: bool = False


    @property
    def integration_ready(self) -> bool:
        """Returns True if all integration checks pass."""
        return all([
            self.config_loaded,
            self.network_connected,
            self.api_connected,
            self.project_selected,
            self.plan_selected,
        ])

    @property
    def status_message(self) -> str:
        """Returns a status message based on the first failed check."""
        if not self.config_loaded:
            return "Configuration not found - run 'nautex setup'"
        if not self.network_connected:
            return "Network connectivity failed - check internet connection"
        if not self.api_connected:
            return "API connectivity failed - check token and API host"
        if not self.project_selected:
            return "Project not selected - run 'nautex setup'"
        if not self.plan_selected:
            return "Implementation plan not selected - run 'nautex setup'"

        if not self.mcp_config_set:
            return "Ready to work, need to setup MCP properly"

        return "Fully integrated and ready to work"

