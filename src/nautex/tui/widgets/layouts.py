"""Layout-related widgets for the Nautex TUI."""

from textual.containers import Vertical, Horizontal


class StepByStepLayout(Vertical):
    """A layout that shows widgets step by step during setup."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.widgets_registry = {}

    def register_widget(self, step_name: str, widget):
        """Register a widget for a specific step.

        Args:
            step_name: Name of the setup step
            widget: Widget to show for that step
        """
        self.widgets_registry[step_name] = widget
        widget.display = False  # Hide initially

    def show_step(self, step_name: str):
        """Show widgets for a specific step.

        Args:
            step_name: Name of the step to show
        """
        # Hide all widgets first
        for widget in self.widgets_registry.values():
            widget.display = False

        # Show only the widgets for the current step and previous steps
        step_order = ["token", "agent_name", "validate", "projects", "plans", "summary"]
        current_index = step_order.index(step_name) if step_name in step_order else 0

        # Show widgets up to current step
        for i in range(current_index + 1):
            if i < len(step_order):
                step = step_order[i]
                if step in self.widgets_registry:
                    self.widgets_registry[step].display = True


class CompactHorizontalLayout(Horizontal):
    """A horizontal layout for side-by-side widgets."""

    DEFAULT_CSS = """
    CompactHorizontalLayout {
        height: auto;
        margin: 1 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs) 