"""Dialog widgets for the Nautex TUI."""

from textual.widgets import Static, Button
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import Screen
from textual import events


class ConfirmationDialog(Screen):
    """A modal screen for yes/no confirmation."""

    DEFAULT_CSS = """
    ConfirmationDialog {
        align: center middle;
    }

    #dialog {
        width: 50;
        height: 11;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #message {
        height: 3;
        text-align: center;
        padding: 1;
    }

    #buttons {
        height: 3;
        align: center middle;
    }

    Button {
        margin: 0 1;
        min-width: 8;
    }
    """

    def __init__(self, message: str, title: str = "Confirm", **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.title = title

    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Static(self.title, id="title")
                    yield Static(self.message, id="message")
                    with Horizontal(id="buttons"):
                        yield Button("Yes", id="yes", variant="primary")
                        yield Button("No", id="no", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "yes":
            self.dismiss(True)
        elif event.button.id == "no":
            self.dismiss(False)

    def on_key(self, event: events.Key) -> None:
        """Handle key events for keyboard shortcuts."""
        if event.key == "escape":
            event.stop()
            self.dismiss(False)
        elif event.key == "enter":
            self.dismiss(True)
        elif event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N"):
            self.dismiss(False) 
