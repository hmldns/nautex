"""Plan context widget for the Nautex TUI."""

from textual.widgets import Static
from textual.containers import Vertical


class PlanContextWidget(Vertical):
    """A widget that displays plan context information."""

    DEFAULT_CSS = """
    PlanContextWidget {
        height: auto;
        border: solid purple;
        margin: 1;
        padding: 1;
    }

    PlanContextWidget > Static {
        height: auto;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content_text = Static("Plan context loading...", id="plan_context_content")

    def compose(self):
        """Compose the plan context widget layout."""
        yield Static("📋 Plan Context", classes="widget_title")
        yield Static("─" * 20)
        yield self.content_text

    def update_from_plan_context(self, plan_context) -> None:
        """Update the widget based on plan context.

        Args:
            plan_context: PlanContext object from plan_context_service
        """
        lines = []

        if plan_context.next_task:
            task = plan_context.next_task
            lines.append(f"🎯 Next Task: {task.task_designator}")
            lines.append(f"📝 {task.name}")
            lines.append(f"📊 Status: {task.status}")
        else:
            lines.append("ℹ️ No tasks available")

        lines.append("")
        lines.append(f"💡 Action: {plan_context.advised_action}")
        lines.append("")
        lines.append(f"⏰ Updated: {plan_context.timestamp}")

        self.content_text.update("\n".join(lines)) 