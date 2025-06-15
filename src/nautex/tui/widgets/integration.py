"""Integration-status-related widgets for the Nautex TUI."""

from textual.widgets import Static
from textual.containers import Vertical
from .status import SetupStatusPanel


class IntegrationStatusWidget(Vertical):
    """A comprehensive status widget tied to the integration status service."""

    DEFAULT_CSS = """
    IntegrationStatusWidget {
        height: auto;
        border: solid blue;
        margin: 1;
        padding: 1;
    }

    IntegrationStatusWidget > Static {
        height: auto;
        margin: 0;
        padding: 0;
    }

    IntegrationStatusWidget > SetupStatusPanel {
        height: auto;
        margin: 1 0;
        padding: 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.status_panel = SetupStatusPanel()
        self.status_text = Static("Checking integration status...", id="status_text")

    def compose(self):
        """Compose the integration status widget layout."""
        yield Static("Integration Status", classes="widget_title")
        yield self.status_panel
        yield Static("─" * 30)
        yield self.status_text

    def update_from_integration_status(self, integration_status) -> None:
        """Update the widget based on integration status.

        Args:
            integration_status: IntegrationStatus object from integration_status_service
        """
        self.status_panel.update_from_integration_status(integration_status)

        # Update status text
        if integration_status.integration_ready:
            self.status_text.update("✅ Ready to work!")
        else:
            self.status_text.update(f"⚠️ {integration_status.status_message}")


# Global shared integration status widget instance
_shared_integration_status_widget = None


def get_shared_integration_status_widget():
    """Get the shared integration status widget instance.

    Returns:
        IntegrationStatusWidget: Shared widget instance
    """
    global _shared_integration_status_widget
    if _shared_integration_status_widget is None:
        _shared_integration_status_widget = IntegrationStatusWidget()
    return _shared_integration_status_widget 