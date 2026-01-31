"""CLI entry point for the scope testing harness."""

import argparse
import asyncio
import sys
from typing import Optional

from rich.console import Console

from .interactive_harness import InteractiveHarness
from .tui import run_tui


console = Console()


def create_mock_harness() -> InteractiveHarness:
    """Create a harness with mock API service (uses MCP layer)."""
    return InteractiveHarness(use_mock=True)


def create_api_harness(project_id: str = None, plan_id: str = None) -> Optional[InteractiveHarness]:
    """Create a harness with real API service.

    Uses same initialization flow as 'nautex mcp' command (DRY).

    Args:
        project_id: Optional project ID override
        plan_id: Optional plan ID override

    Returns:
        InteractiveHarness or None if API not configured
    """
    try:
        from nautex.services import ConfigurationService, init_mcp_services

        # Load configuration (same as main CLI)
        config_service = ConfigurationService()
        config = config_service.load_configuration()
        if not config:
            console.print("[red]Error: Nautex not configured. Run 'nautex setup' first.[/red]")
            return None

        # Override project/plan if provided
        if project_id:
            config_service.config.project_id = project_id
        if plan_id:
            config_service.config.plan_id = plan_id

        # Initialize MCP services (same flow as 'nautex mcp')
        init_mcp_services(config_service)

        # Return harness without mock setup (MCP already configured)
        return InteractiveHarness(use_mock=False)

    except Exception as e:
        console.print(f"[red]Error creating API harness: {e}[/red]")
        return None


async def run_simple_test(harness: InteractiveHarness) -> None:
    """Run a simple non-interactive test - accumulating log format."""
    console.print("[bold]MCP Layer Test Log[/bold]")
    console.print("[dim]" + "=" * 60 + "[/dim]\n")

    # Test compact mode (default)
    console.print("[cyan]>>> mcp_handle_next_scope(full=False)[/cyan]")
    output = await harness.cmd_next(full=False)
    console.print(output)
    console.print()

    # Test full mode
    console.print("[cyan]>>> mcp_handle_next_scope(full=True)[/cyan]")
    output = await harness.cmd_next(full=True)
    console.print(output)
    console.print()

    # Verify stateless - compact again should be same as first
    console.print("[cyan]>>> mcp_handle_next_scope(full=False)[/cyan]")
    output = await harness.cmd_next(full=False)
    console.print(output)
    console.print()

    console.print("[dim]" + "=" * 60 + "[/dim]")
    console.print("[green]All calls went through actual MCP layer.[/green]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test harness for full/compact scope rendering (uses MCP layer)"
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "api"],
        default="mock",
        help="Data source mode (default: mock)"
    )
    parser.add_argument(
        "--project-id",
        help="Project ID for API mode (uses config if not provided)"
    )
    parser.add_argument(
        "--plan-id",
        help="Plan ID for API mode (uses config if not provided)"
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run simple test instead of TUI"
    )

    args = parser.parse_args()

    # Create harness
    if args.mode == "mock":
        harness = create_mock_harness()
    else:
        harness = create_api_harness(args.project_id, args.plan_id)
        if harness is None:
            sys.exit(1)

    # Run TUI or simple test
    if args.no_tui:
        asyncio.run(run_simple_test(harness))
    else:
        run_tui(harness)


if __name__ == "__main__":
    main()
