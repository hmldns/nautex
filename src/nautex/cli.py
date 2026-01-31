# import logging
#
# logging.basicConfig(
#     level=logging.ERROR
# )

import argparse
import asyncio

import sys

from pathlib import Path

from .services.ui_service import UIService
from .services.config_service import ConfigurationService
from .services.nautex_api_service import NautexAPIService
from .services.integration_status_service import IntegrationStatusService
from .services.document_service import DocumentService
from .services.mcp_service import mcp_server_run, mcp_handle_next_scope, mcp_handle_status
from .services.init import init_mcp_services
from .services.mcp_config_service import MCPConfigService
from .services.agent_rules_service import AgentRulesService
from .api import create_api_client
from .models.config import MCPOutputFormat
from .models.mcp import format_response_as_markdown
from . import __version__
import json


def handle_test_commands(args, config_service):
    """Handle test commands for MCP functionality.

    Args:
        args: Command line arguments
        config_service: Configuration service instance
    """
    use_yaml = config_service.config.response_format == MCPOutputFormat.MD_YAML

    if args.test_command == "next_scope":
        result = asyncio.run(mcp_handle_next_scope())
        data = result.get("data", result) if result.get("success") else result

        if use_yaml:
            print(format_response_as_markdown("Next Scope", data))
        else:
            print(json.dumps(data, indent=4))

    elif args.test_command == "status":
        result = asyncio.run(mcp_handle_status())
        data = result.get("data", result) if result.get("success") else result

        if use_yaml:
            print(format_response_as_markdown("Status", data))
        else:
            print(json.dumps(data, indent=4))
    else:
        print("Please specify a test command. Available commands: next_scope, status.")


def main() -> None:
    """Main entry point for the Nautex CLI."""
    parser = argparse.ArgumentParser(
        prog="nautex",
        description="nautex - Nautex AI platform MCP integration tool and server"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Interactive setup configuration")

    # Status command  
    status_parser = subparsers.add_parser("status", help="View integration status")
    status_parser.add_argument("--noui", action="store_true", help="Print status to console instead of TUI")

    # MCP command
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server for IDE integration")

    # MCP subcommands
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", help="MCP commands")

    # MCP test command
    mcp_test_parser = mcp_subparsers.add_parser("test", help="Test MCP functionality")
    mcp_test_subparsers = mcp_test_parser.add_subparsers(dest="test_command", help="Test commands")

    # MCP test commands
    mcp_test_next_scope_parser = mcp_test_subparsers.add_parser("next_scope", help="Test next_scope functionality")
    mcp_test_status_parser = mcp_test_subparsers.add_parser("status", help="Test status functionality")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # 1. Base services that don't depend on other services
    config_service = ConfigurationService()
    config_service.load_configuration()

    # 2. Initialize services that depend on config
    mcp_config_service = MCPConfigService(config_service)
    agent_rules_service = AgentRulesService(config_service)

    # 3. Initialize API client and service if config is available

    api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
    nautex_api_service = NautexAPIService(api_client, config_service)

    # 4. Services that depend on other services
    integration_status_service = IntegrationStatusService(
        config_service=config_service,
        mcp_config_service=mcp_config_service,
        agent_rules_service=agent_rules_service,
        nautex_api_service=nautex_api_service,
    )


    # Initialize document service
    document_service = DocumentService(
        nautex_api_service=nautex_api_service,
        config_service=config_service
    )

    # 5. UI service for TUI commands
    ui_service = UIService(
        config_service=config_service,
        integration_status_service=integration_status_service,
        api_service=nautex_api_service,
        mcp_config_service=mcp_config_service,
        agent_rules_service=agent_rules_service,
    )

    # Command dispatch
    if args.command == "setup":
        # Run the interactive setup TUI
        asyncio.run(ui_service.handle_setup_command())

    elif args.command == "status":
        # Run the status command
        asyncio.run(ui_service.handle_status_command(noui=args.noui))

    elif args.command == "mcp":
        # Initialize MCP service using shared init function (reuse existing services)
        try:
            init_mcp_services(
                config_service=config_service,
                integration_status_service=integration_status_service,
                nautex_api_service=nautex_api_service,
                document_service=document_service,
            )

            # Check for MCP subcommands
            if args.mcp_command == "test":
                handle_test_commands(args, config_service)
            else:
                # Run the MCP server in the main thread
                mcp_server_run()

        except Exception as e:
            print(f"MCP server error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main() 
