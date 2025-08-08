from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from .config import NautexConfig
from ..api.api_models import AccountInfo, ImplementationPlan
from ..prompts.consts import CMD_NAUTEX_SETUP
from ..utils.mcp_utils import MCPConfigStatus
from ..agent_setups.base import AgentRulesStatus


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

    implementation_plan: Optional[ImplementationPlan] = None

    @property
    def project_selected(self):
        return self.config and self.config.project_id

    @property
    def plan_selected(self):
        return self.config and self.config.plan_id

    @property
    def agent_type_selected(self):
        return self.config.agent_type_selected

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
            self.agent_type_selected,
            self.mcp_config_set,
            self.agent_rules_set,
        ])


    def get_status_message(self, from_mcp: bool = False) -> str:
        """Returns a status message based on the first failed check.

        Args:
            from_mcp: If True, adds CMD_NAUTEX_SETUP suggestion at the beginning.
                     If False, provides original UI-specific actions.
        """
        mcp_prefix = f"Run '{CMD_NAUTEX_SETUP}' to configure, then " if from_mcp else ""

        if not self.config_loaded:
            return f"Configuration not found - run '{CMD_NAUTEX_SETUP}'"
        if not self.network_connected:
            return f"Network connectivity failed - {mcp_prefix}check internet connection or Host URL"
        if not self.api_connected:
            return f"API connectivity failed - {mcp_prefix}check token"
        if not self.project_selected:
            return f"Project not selected - {mcp_prefix}select project from list"
        if not self.plan_selected:
            return f"Implementation plan not selected - {mcp_prefix}select plan in list"

        if not self.agent_type_selected:
            return f"Agent type not selected - {mcp_prefix}press 'Ctrl+Y' to select agent type"

        if not self.mcp_config_set:
            return f"MCP configuration needed - {mcp_prefix}press 'Ctrl+T' to configure MCP integration"

        if not self.agent_rules_set:
            return f"Agent rules needed - {mcp_prefix}press 'Ctrl+R' to configure agent workflow rules"

        return f"Fully integrated and ready to work"
