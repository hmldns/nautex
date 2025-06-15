"""View-related widgets for the Nautex TUI."""

from textual.widgets import Static


class ConfigurationSummaryView(Static):
    """A read-only view of the full configuration."""

    def __init__(self, **kwargs):
        super().__init__("Configuration summary will appear here", **kwargs)

    def show_config(self, config_data: dict) -> None:
        """Display configuration summary.

        Args:
            config_data: Configuration data to display
        """
        lines = []
        lines.append("📋 Configuration Summary")
        lines.append("=" * 25)

        for key, value in config_data.items():
            # Format the key nicely
            display_key = key.replace('_', ' ').title()

            # Handle different value types
            if isinstance(value, bool):
                display_value = "✅ Yes" if value else "❌ No"
            elif isinstance(value, str) and value:
                # Mask sensitive values
                if any(sensitive in key.lower() for sensitive in ['token', 'key', 'password']):
                    display_value = "*" * min(len(value), 8) + "..."
                else:
                    display_value = value
            elif isinstance(value, (int, float)):
                display_value = str(value)
            elif value is None:
                display_value = "Not set"
            else:
                display_value = str(value)

            lines.append(f"{display_key}: {display_value}")

        self.update("\n".join(lines)) 