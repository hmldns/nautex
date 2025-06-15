"""Input-related widgets for the Nautex TUI."""

from textual.widgets import Input, Label
from textual.containers import Vertical
from textual.widgets import Link, Static


class CompactInput(Vertical):
    """A compact input field with minimal spacing."""

    DEFAULT_CSS = """
    CompactInput {
        height: auto;
        margin: 0;
        padding: 0;
    }

    CompactInput > Label {
        margin: 0 0 1 0;
        padding: 0;
        height: 1;
    }

    CompactInput > Input {
        margin: 0;
        padding: 0;
        height: 3;
    }
    """

    def __init__(self, title: str, placeholder: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)

    def compose(self):
        """Compose the compact input layout."""
        yield self.title_label
        yield self.input_field

    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value

    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value

    def focus(self) -> None:
        """Focus the input field."""
        self.input_field.focus()


class ApiTokenInput(Vertical):
    """A compact API token input with help text and link."""

    DEFAULT_CSS = """
    ApiTokenInput {
        height: auto;
        margin: 0;
        padding: 0;
    }

    ApiTokenInput > Label {
        margin: 0 0 1 0;
        padding: 0;
        height: 1;
    }

    ApiTokenInput > Input {
        margin: 0;
        padding: 0;
        height: 3;
    }

    ApiTokenInput > Static {
        height: 1;
        margin: 1 0 0 0;
        padding: 0;
        color: $text-muted;
    }
    """

    def __init__(self, title: str = "API Token", placeholder: str = "Enter your Nautex.ai API token...", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)
        self.help_text = Static("Get your API token from: [link=https://app.nautex.ai/new_token]app.nautex.ai/new_token[/link]", markup=True)

    def compose(self):
        """Compose the API token input layout."""
        yield self.title_label
        yield self.input_field
        yield self.help_text

    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value

    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value

    def focus(self) -> None:
        """Focus the input field."""
        self.input_field.focus()


class TitledInput(Vertical):
    """An input field with a title and optional validation state."""

    def __init__(self, title: str, placeholder: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)

    def compose(self):
        """Compose the input layout."""
        yield self.title_label
        yield self.input_field

    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value

    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value 