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
from .services.mcp_service import MCPService
from .api.client import NautexAPIClient


async def handle_mcp_command() -> None:
    """Handle the MCP server command."""
    config = None
    nautex_api_service = None
    config_service = ConfigurationService()
    
    try:
        # Try to load configuration, but don't fail if it's not available
        config = config_service.load_configuration()
        
        # Initialize API client and services only if config is loaded
        api_client = NautexAPIClient(base_url="https://api.nautex.ai")
        nautex_api_service = NautexAPIService(api_client, config)
        
    except ConfigurationError as e:
        # Configuration is not available - we'll start MCP server anyway
        # but with limited functionality
        print(f"Warning: Configuration not available: {e}", file=sys.stderr)
        print("MCP server starting with limited functionality. Use 'nautex setup' to configure.", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Unexpected error loading configuration: {e}", file=sys.stderr)
        print("MCP server starting with limited functionality.", file=sys.stderr)
    
    try:
        # Initialize services with new architecture
        from .services.mcp_config_service import MCPConfigService
        mcp_config_service = MCPConfigService()
        integration_status_service = IntegrationStatusService(
            config_service=config_service,
            mcp_config_service=mcp_config_service
        )
        plan_context_service = PlanContextService(
            integration_status_service=integration_status_service
        )
        
        # Initialize and start MCP service (pass None if config not available)
        mcp_service = MCPService(
            config=config,  # This can be None now
            nautex_api_service=nautex_api_service,  # This can be None now
            plan_context_service=plan_context_service
        )
        
        # Start the MCP server
        mcp_service.start()
        
    except Exception as e:
        print(f"MCP server error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main entry point for the Nautex CLI."""
    parser = argparse.ArgumentParser(
        prog="nautex",
        description="Nautex CLI - Interface with Nautex.ai platform API"
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
    
    # Command dispatch
    if args.command == "setup":
        # Run the interactive setup TUI
        project_root = Path.cwd()
        ui_service = UIService(project_root)
        asyncio.run(ui_service.handle_setup_command())
        
    elif args.command == "status":
        # Run the status command
        project_root = Path.cwd()
        ui_service = UIService(project_root)
        asyncio.run(ui_service.handle_status_command(noui=args.noui))
            
    elif args.command == "mcp":
        asyncio.run(handle_mcp_command())


if __name__ == "__main__":
    main() 