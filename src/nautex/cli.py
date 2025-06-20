"""Main CLI entry point for Nautex CLI."""

import argparse
import asyncio
import sys
from typing import Optional
from pathlib import Path

from .services.ui_service import UIService
from .services.config_service import ConfigurationService, ConfigurationError
from .services.nautex_api_service import NautexAPIService
from .services.integration_status_service import IntegrationStatusService
from .services.plan_context_service import PlanContextService
from .services.mcp_service import MCPService, mcp_server_set_service_instance, mcp_server_run
from .services.mcp_config_service import MCPConfigService
from .api.client import NautexAPIClient
from .api import create_api_client


def main() -> None:
    """Main entry point for the Nautex CLI."""
    parser = argparse.ArgumentParser(
        prog="nautex",
        description="nautex - Nautex AI platform MCP integration tool and server"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Interactive setup configuration")

    # Status command  
    status_parser = subparsers.add_parser("status", help="View integration status")
    status_parser.add_argument("--noui", action="store_true", help="Print status to console instead of TUI")

    # MCP command
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server for IDE integration")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # Initialize all common services before checking the command
    project_root = Path.cwd()

    # 1. Base services that don't depend on other services
    config_service = ConfigurationService(project_root)
    mcp_config_service = MCPConfigService()

    # 2. Load configuration or set default
    config = config_service.load_configuration()

    # 3. Initialize API client and service if config is available

    api_client = create_api_client(base_url=config.api_host, test_mode=config.api_test_mode)
    nautex_api_service = NautexAPIService(api_client, config)

    # 4. Services that depend on other services
    integration_status_service = IntegrationStatusService(
        config_service=config_service,
        mcp_config_service=mcp_config_service,
        nautex_api_service=nautex_api_service,
        project_root=project_root
    )

    plan_context_service = PlanContextService(
        integration_status_service=integration_status_service
    )

    # 5. UI service for TUI commands
    ui_service = UIService(
        config_service=config_service,
        plan_context_service=plan_context_service,
        integration_status_service=integration_status_service,
        api_service=nautex_api_service,
        project_root=project_root
    )

    # Command dispatch
    if args.command == "setup":
        # Run the interactive setup TUI
        asyncio.run(ui_service.handle_setup_command())

    elif args.command == "status":
        # Run the status command
        asyncio.run(ui_service.handle_status_command(noui=args.noui))

    elif args.command == "mcp":
        # Handle MCP command without asyncio.run
        if not nautex_api_service:
            print("MCP server starting with limited functionality. Use 'nautex setup' to configure.", file=sys.stderr)

        try:
            # Initialize MCP service
            mcp_service = MCPService(
                config=config,  # This can be None
                nautex_api_service=nautex_api_service,  # This can be None
                plan_context_service=plan_context_service
            )

            # Set the global MCP service instance
            mcp_server_set_service_instance(mcp_service)

            # Run the MCP server in the main thread
            mcp_server_run()

        except Exception as e:
            print(f"MCP server error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main() 
