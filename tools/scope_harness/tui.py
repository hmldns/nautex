"""TUI interface for testing full/compact scope rendering."""

import asyncio
from typing import List, Set

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich import box

from nautex.api.scope_context_model import TaskStatus
from .interactive_harness import InteractiveHarness


class ScopeTestTUI:
    """TUI with task selection panel and command bar for testing scope rendering."""

    def __init__(self, harness: InteractiveHarness):
        self.harness = harness
        self.console = Console()
        self.selected_tasks: Set[str] = set()
        self.cursor_index: int = 0
        self.transaction_log: List[str] = []  # Accumulated log of all MCP calls
        self.task_list: List[tuple] = []

    def _refresh_task_list(self) -> None:
        """Refresh the task list from tree state service."""
        self.task_list = self.harness.task_tree.get_flattened_tree()

    def _cursor_to_first_focus(self) -> None:
        """Move cursor to first focus task after scope updates."""
        self._refresh_task_list()
        for i, (designator, _, _, _) in enumerate(self.task_list):
            if self.harness.task_tree.is_focus_task(designator):
                self.cursor_index = i
                return

    def _render_task_tree(self) -> Panel:
        """Render the selectable task tree with status indicators."""
        self._refresh_task_list()

        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("", width=3)
        table.add_column("Task", width=50)
        table.add_column("Status", width=15)
        table.add_column("F", width=2)
        table.add_column("O", width=2)

        for i, (designator, name, status, depth) in enumerate(self.task_list):
            if designator in self.selected_tasks:
                sel = "[green]\u2713[/green]"
            elif i == self.cursor_index:
                sel = "[yellow]>[/yellow]"
            else:
                sel = " "

            indent = "  " * depth
            # White designator, dimmed name
            if i == self.cursor_index:
                task_display = f"{indent}[bold white]{designator}[/bold white] [dim]{name}[/dim]"
            else:
                task_display = f"{indent}[white]{designator}[/white] [dim]{name}[/dim]"

            status_style = {
                TaskStatus.NOT_STARTED: "dim",
                TaskStatus.IN_PROGRESS: "yellow",
                TaskStatus.DONE: "green",
                TaskStatus.BLOCKED: "red",
            }.get(status, "")

            status_text = f"[{status_style}]{status.value}[/{status_style}]"

            focus_col = "[cyan]\u2605[/cyan]" if self.harness.task_tree.is_focus_task(designator) else ""
            optimistic_col = "[yellow]o[/yellow]" if self.harness.task_tree.is_optimistic(designator) else ""

            table.add_row(sel, task_display, status_text, focus_col, optimistic_col)

        return Panel(table, title="Tasks", border_style="blue")

    def _render_output(self) -> Panel:
        """Render the MCP transaction log panel."""
        if self.transaction_log:
            # Join all log entries with separator
            full_log = "\n---\n".join(self.transaction_log)
            content = Markdown(full_log)
        else:
            content = Text("Press 'n' for compact or 'f' for full mode", style="dim")

        title = f"MCP Transaction Log ({len(self.transaction_log)} calls)"

        return Panel(content, title=title, border_style="green")

    def _render_command_bar(self) -> Text:
        """Render the command bar."""
        commands = [
            ("[n]ext", "compact"),
            ("[f]ull", "full tree"),
            ("[d]one", ""),
            ("[i]n-progress", ""),
            ("[b]locked", ""),
            ("[s]tart", "not started"),
            ("[r]eset", "state"),
            ("[c]lear", "log"),
            ("[q]uit", ""),
        ]

        text = Text()
        for cmd, desc in commands:
            text.append(cmd, style="bold cyan")
            if desc:
                text.append(f" {desc}", style="dim")
            text.append("  ")

        return text

    def _render_screen(self) -> None:
        """Render the full screen."""
        self.console.clear()
        self.console.print(self._render_output())
        self.console.print(self._render_task_tree())
        self.console.print(Panel(self._render_command_bar(), border_style="dim"))

    def _log(self, cmd: str, response: str) -> None:
        """Append command and response to transaction log."""
        entry = f"**>>> {cmd}**\n\n{response}"
        self.transaction_log.append(entry)

    async def _handle_next(self, full: bool = False) -> None:
        """Handle next_scope command."""
        cmd = f"mcp_handle_next_scope(full={full})"
        output = await self.harness.cmd_next(full=full)
        self._log(cmd, output)
        self._cursor_to_first_focus()

    async def _handle_update(self, status: TaskStatus) -> None:
        """Handle task status update."""
        tasks_to_update = list(self.selected_tasks)
        if not tasks_to_update and self.task_list:
            tasks_to_update = [self.task_list[self.cursor_index][0]]

        if tasks_to_update:
            updates = [(d, status) for d in tasks_to_update]
            ops_str = ", ".join([f'{{"{d}", "{status.value}"}}' for d in tasks_to_update])
            cmd = f"mcp_handle_update_tasks([{ops_str}])"
            msg = await self.harness.cmd_batch_update(updates)
            self._log(cmd, msg)

            self.selected_tasks.clear()
            self._cursor_to_first_focus()

    def _move_cursor(self, delta: int) -> None:
        """Move cursor up/down."""
        if self.task_list:
            self.cursor_index = (self.cursor_index + delta) % len(self.task_list)

    def _toggle_selection(self) -> None:
        """Toggle selection of current task."""
        if self.task_list:
            designator = self.task_list[self.cursor_index][0]
            if designator in self.selected_tasks:
                self.selected_tasks.remove(designator)
            else:
                self.selected_tasks.add(designator)

    async def run(self) -> None:
        """Run the TUI event loop."""
        try:
            import readchar
        except ImportError:
            self.console.print("[red]Error: readchar package required for TUI.[/red]")
            self.console.print("Install with: pip install readchar")
            return

        while True:
            self._render_screen()

            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                break

            if key == 'q':
                break
            elif key == 'n':
                await self._handle_next(full=False)
            elif key == 'f':
                await self._handle_next(full=True)
            elif key == 'd':
                await self._handle_update(TaskStatus.DONE)
            elif key == 'i':
                await self._handle_update(TaskStatus.IN_PROGRESS)
            elif key == 'b':
                await self._handle_update(TaskStatus.BLOCKED)
            elif key == 's':
                await self._handle_update(TaskStatus.NOT_STARTED)
            elif key == 'r':
                msg = self.harness.cmd_reset()
                self._log("reset()", f"```\n{msg}\n```")
                self.selected_tasks.clear()
                self._cursor_to_first_focus()
            elif key == 'c':
                self.transaction_log.clear()
            elif key == ' ':
                self._toggle_selection()
            elif key == readchar.key.UP or key == 'k':
                self._move_cursor(-1)
            elif key == readchar.key.DOWN or key == 'j':
                self._move_cursor(1)

        self.console.clear()
        self.console.print("Goodbye!")


def run_tui(harness: InteractiveHarness) -> None:
    """Run the TUI with the given harness."""
    tui = ScopeTestTUI(harness)
    asyncio.run(tui.run())
