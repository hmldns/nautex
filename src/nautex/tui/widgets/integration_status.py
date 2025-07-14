from textual.widgets import Static, Button, Digits
from textual.containers import Horizontal, HorizontalGroup


from ...models.integration_status import IntegrationStatus


class StatusDisplay(Static):
    """A read-only display for a single status item."""

    DEFAULT_CSS = """
    StatusDisplay {
        height: auto;
        width: auto;
        margin: 0 1 0 0;
        padding: 0;
        min-width: 10;
    }
    """

    def __init__(self, label: str, status: bool = False, **kwargs):
        """Initialize status display.

        Args:
            label: The label text
            status: The status indicator (emoji)
        """
        self.label_text = label
        self.status_flag = status
        super().__init__(self._disp_render(), **kwargs)


    def set_status(self, flag: bool):
        self.status_flag = flag

    def _disp_render_status(self) -> str:
        return "✅" if self.status_flag else "⚠️"

    def _disp_render(self) -> str:
        return f"{self._disp_render_status()} {self.label_text}"

    def update_status(self, status_flag: bool) -> None:
        self.set_status(status_flag)
        self.update(self._disp_render())


class IntegrationStatusPanel(HorizontalGroup):
    """A horizontal strip of StatusDisplay widgets for integration status."""
    #
    DEFAULT_CSS = """
    IntegrationStatusPanel {
        width: 1fr;
        height: auto;
        width: 100%;
        border: solid $primary;
    }

    IntegrationStatusPanel StatusDisplay {
        height: auto;
        margin: 0 1 0 0;
        padding: 1 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.status_network = StatusDisplay("Connection")
        self.status_api =     StatusDisplay("API")
        self.status_project = StatusDisplay("Project")
        self.status_plan =    StatusDisplay("Plan")
        self.status_mcp =     StatusDisplay("MCP Config")
        self.agent_rules =     StatusDisplay("Agent Rules")


        self.border_title = "Integration Status"

    def compose(self):
        """Compose the status panel layout."""
        yield self.status_network
        yield self.status_api
        yield self.status_project
        yield self.status_plan
        yield self.status_mcp


    def update_data(self, integration_status: IntegrationStatus) -> None:
        # Network status

        self.status_network.update_status(integration_status.network_connected)
        self.status_api.update_status(integration_status.api_connected)

        # self.update_status("network", "🟢" if integration_status.network_connected
        # else "🔴" if integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get(
        #     "has_token")
        # else "⚪")
        #
        # # API status
        # self.update_status("api", "🟢" if integration_status.api_connected
        # else "🔴" if integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get(
        #     "has_token") and integration_status.network_connected
        # else "⚪")
        #
        # # Project status
        # self.update_status("project",
        #                    "🟢" if integration_status.config_summary and integration_status.config_summary.get(
        #                        "project_id")
        #                    else "⚪")
        #
        # # Plan status
        # self.update_status("plan",
        #                    "🟢" if integration_status.config_summary and integration_status.config_summary.get("plan_id")
        #                    else "⚪")
        #
        # # MCP status
        # self.update_status("mcp", "🟢" if integration_status.mcp_status == MCPConfigStatus.OK
        # else "🔴" if integration_status.mcp_status == MCPConfigStatus.MISCONFIGURED
        # else "⚪")
