"""Centralized TUI styling constants for the Nautex CLI."""


class Colors:
    """Color constants for TUI elements."""
    PRIMARY = "#0078d4"
    SUCCESS = "#107c10"
    WARNING = "#ffb900"
    ERROR = "#d13438"
    SECONDARY = "#605e5c"


class StatusIndicators:
    """Emoji indicators for status display."""
    SUCCESS = "🟢"
    ERROR = "🔴"
    WARNING = "🟡"
    PENDING = "⚪"


class Styles:
    """CSS-like styling constants for Textual widgets."""
    PANEL_BORDER = "solid"
    INPUT_BORDER = "round"
    BUTTON_STYLE = "bold" 