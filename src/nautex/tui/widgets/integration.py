"""Integration-status-related widgets for the Nautex TUI."""

from textual.widgets import Static
from textual.containers import Vertical
from .integration_status import IntegrationStatusPanel


class IntegrationStatusWidget(Vertical):
    """A simple 2-line status widget for terminal display."""

    DEFAULT_CSS = """
    IntegrationStatusWidget {
        height: auto;
        margin: 0;
        padding: 0;
    }

    IntegrationStatusWidget Static {
        margin: 0;
        padding: 0;
    }

    IntegrationStatusWidget IntegrationStatusPanel {
        margin: 0;
        padding: 0;
    }
    """

    # DEFAULT_CSS = """
    # IntegrationStatusWidget {
    #     height: 5;
    #     margin: 0;
    #     padding: 0;
    # }
    #
    # IntegrationStatusWidget > Static {
    #     margin: 0;
    #     padding: 0;
    # }
    #
    # IntegrationStatusWidget > IntegrationStatusPanel {
    #     margin: 0;
    #     padding: 0;
    # }
    # """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.status_panel = IntegrationStatusPanel()
        self.status_text = Static("Checking status...", id="status_text")

    def compose(self):
        """Compose the integration status widget layout."""
        yield self.status_panel
        yield self.status_text

    def update_from_integration_status(self, integration_status) -> None:
        """Update the widget based on integration status.

        Args:
            integration_status: IntegrationStatus object from integration_status_service
        """
        self.status_panel.update_from_integration_status(integration_status)

        # Update status text
        if integration_status.integration_ready:
            self.status_text.update("✅ Ready to work")
        else:
            self.status_text.update(f"⚠️ {integration_status.status_message}")
