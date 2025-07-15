from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from .config import NautexConfig
from ..api.api_models import AccountInfo
from ..services.mcp_config_service import MCPConfigStatus
from ..services.agent_rules_service import AgentRulesStatus


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

    # MCP configuration status
    mcp_status: MCPConfigStatus = MCPConfigStatus.NOT_FOUND
    mcp_config_path: Optional[Path] = None

    # Agent rules status
    agent_rules_status: AgentRulesStatus = AgentRulesStatus.NOT_FOUND
    agent_rules_path: Optional[Path] = None

    @property
    def project_selected(self):
        return self.config and self.config.project_id

    @property
    def plan_selected(self):
        return self.config and self.config.plan_id


    @property
    def mcp_config_set(self):
        return self.mcp_status == MCPConfigStatus.OK

    @property
    def agent_rules_set(self):
        return self.agent_rules_status == AgentRulesStatus.OK

    @property
    def integration_ready(self) -> bool:
        """Returns True if all integration checks pass."""
        return all([
            self.config_loaded,
            self.network_connected,
            self.api_connected,
            self.project_selected,
            self.plan_selected,
            self.mcp_config_set,
            self.agent_rules_set,
        ])

    @property
    def status_message(self) -> str:
        """Returns a status message based on the first failed check."""
        if not self.config_loaded:
            return "Configuration not found - run 'uv nautex setup'"
        if not self.network_connected:
            return "Network connectivity failed - check internet connection or Host URL"
        if not self.api_connected:
            return "API connectivity failed - check token"
        if not self.project_selected:
            return "Project not selected - run 'uv nautex setup'"
        if not self.plan_selected:
            return "Implementation plan not selected - run 'uv nautex setup'"

        if not self.mcp_config_set:
            return "MCP configuration needed - press 'M' to configure MCP integration"

        if not self.agent_rules_set:
            return "Agent rules needed - press 'A' to configure agent workflow rules"

        return "Fully integrated and ready to work"
