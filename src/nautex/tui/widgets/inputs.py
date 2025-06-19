"""Input-related widgets for the Nautex TUI."""

from typing import Callable, Optional, Union, Awaitable

from textual.widgets import Input, Label
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Markdown


class ValidatedTextInput(Vertical):
    """A text input with validation, check mark, and error message."""

    DEFAULT_CSS = """
    ValidatedTextInput {
        height: auto;
        margin: 0;
        padding: 0;
        border: solid $primary;
        padding: 0;
    }

    ValidatedTextInput > .title-row {
        height: 1;
        margin: 0 0 1 0;
        padding: 0;
    }

    ValidatedTextInput > .input-row {
        height: 3;
        margin: 0;
        padding: 0;
    }

    ValidatedTextInput > .error-row {
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        color: $error;
    }

    ValidatedTextInput .check-mark {
        width: 1;
        height: 1;
        margin: 0;
        padding: 0;
        color: $success;
    }

    ValidatedTextInput .error-mark {
        width: 1;
        height: 1;
        margin: 0;
        padding: 0;
        color: $error;
    }
    """

    def __init__(
        self, 
        title: str, 
        placeholder: str = "", 
        validator: Optional[Callable[[str], Awaitable[tuple[bool, str]]]] = None,
        title_extra: Optional[Union[Static, Markdown]] = None,
        default_value: str = "",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.border_title = title
        self.placeholder = placeholder
        self.validator = validator
        self.title_extra = title_extra
        self.default_value = default_value

        # Create widgets
        self.input_field = Input(placeholder=placeholder, value=default_value)
        self.status_mark = Static("a", classes="check-mark")
        self.error_text = Static("", classes="error-row")

        # Track validation state
        self.is_valid = True
        self.error_message = ""

    def compose(self):
        """Compose the validated input layout."""
        with Horizontal(classes="title-row"):
            if self.title_extra:
                yield self.title_extra

        with Horizontal(classes="input-row"):
            yield self.input_field
            yield self.status_mark

        yield self.error_text

    def on_mount(self):
        """Called when the widget is mounted."""
        # Validate the initial value when the widget is mounted
        self.app.call_later(self.validate_initial)

    async def validate_initial(self):
        """Validate the initial value."""
        if self.validator:
            await self.validate()

    async def on_input_value_changed(self, event):
        """Handle input value changes and validate."""
        if self.validator:
            await self.validate()

    async def validate(self) -> bool:
        """Validate the current input value."""
        if self.validator:
            self.is_valid, self.error_message = await self.validator(self.value)

            if self.is_valid:
                self.status_mark.update("✓")
                self.status_mark.remove_class("error-mark")
                self.status_mark.add_class("check-mark")
                self.error_text.update("")
            else:
                self.status_mark.update("✗")
                self.status_mark.remove_class("check-mark")
                self.status_mark.add_class("error-mark")
                self.error_text.update(self.error_message)

        return self.is_valid

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