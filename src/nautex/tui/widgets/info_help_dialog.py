"""Info and Help dialog widget for the Nautex TUI."""

from textual.widgets import Button, Markdown
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import ModalScreen
from textual import events

from ... import __version__

# Dialog content as markdown
HELP_CONTENT = f"""
# 🚀 Nautex - AI-Powered Development

**Version: {__version__}**

## 📋 About
Nautex is a requirements-first development platform that helps Coding Agents to execute better by detailed and complete system design and detailed plan.

[GitHub Repository](https://github.com/hmldns/nautex)

Created by [Ivan Makarov](https://x.com/ivan_mkrv)

## 💬 Join Our Community!
Get help, share ideas, and connect with other developers
[🎮 Join Discord Server](https://discord.gg/nautex)


## ⌨️ Keyboard Shortcuts
- **Ctrl+C / ESC**: Quit
- **Tab / Enter**: Navigate fields
- **Ctrl+T**: MCP Config
- **Ctrl+R**: Agent Rules
- **Ctrl+Y**: Select Agent Type
- **F1**: Show this help
"""


class InfoHelpDialog(ModalScreen):
    """A modal screen displaying info, help, and community links."""

    DEFAULT_CSS = """
    InfoHelpDialog {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: auto;
        max-height: 80vh;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #content {
        height: auto;
        max-height: 40;
        overflow-y: auto;
        margin-bottom: 1;
    }

    #buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Markdown(HELP_CONTENT, id="content")
                    with Horizontal(id="buttons"):
                        yield Button("Close", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "close":
            self.dismiss()

    def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        if event.key in ("escape", "f1"):
            event.stop()
            self.dismiss()
        elif event.key == "enter":
            self.dismiss()