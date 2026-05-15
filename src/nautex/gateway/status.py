"""Agent capability status reporting.

Pure formatter over `list_available_agents()` — reports what the
gateway can launch and which dependencies are present. No side
effects, no install logic (that lives in `adapter_install`).
"""

from __future__ import annotations

import io

from rich.console import Console
from rich.table import Table

from .adapter_install import NPM_ADAPTER_PACKAGES
from .config import list_available_agents


def _dependency_label(executable: str) -> str:
    if executable in NPM_ADAPTER_PACKAGES:
        return "ACP adapter"
    return "native support"


def format_status_report() -> str:
    """Render the agent capability table as a string."""
    agents = list_available_agents()

    table = Table(show_lines=False, header_style="bold")
    table.add_column("AGW entry")
    table.add_column("Executable")
    table.add_column("ACP Dependency")
    table.add_column("Status")

    ready_count = 0
    for agent_id, info in agents.items():
        reg = info["registration"]
        if info["installed"]:
            ready_count += 1
            status = "[green]ready[/green]"
        else:
            status = "[red]missing[/red]"
        table.add_row(agent_id, reg.executable, _dependency_label(reg.executable), status)

    missing_npm = [
        agent_id for agent_id, info in agents.items()
        if not info["installed"] and info["registration"].executable in NPM_ADAPTER_PACKAGES
    ]

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=120)
    console.print(table)
    console.print(f"{ready_count} of {len(agents)} agents ready.")
    if missing_npm:
        console.print(
            "Run [bold]`uvx nautex gateway setup --auth-token <TOKEN>`[/bold] to install missing ACP adapters."
        )
    return buf.getvalue().rstrip()
