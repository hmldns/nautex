import argparse
import asyncio
import json
import os
import platform
import sys
import uuid

from .models.config import MCPOutputFormat
from .models.mcp import format_response_as_markdown
from .services.config_service import ConfigurationService
from .services.mcp_service import mcp_server_run
from .services.init import init_mcp_services
from .services.mcp_config_service import MCPConfigService
from .services.agent_rules_service import AgentRulesService
from .services.integration_status_service import IntegrationStatusService
from .services.nautex_api_service import NautexAPIService
from .services.document_service import DocumentService
from .services.ui_service import UIService
from .api import create_api_client
from . import __version__


GATEWAY_WS_PATH = "/agw-node/ws"


def _derive_ws_url(api_host: str) -> str:
    """Derive WebSocket uplink URL from the HTTP API host."""
    url = api_host.rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    return url + GATEWAY_WS_PATH


# ---------------------------------------------------------------------------
# CLI command registration and dispatch
# ---------------------------------------------------------------------------

# Commands that require init_mcp_services() before dispatch
CLI_COMMANDS = {"status", "next-scope", "update-tasks", "submit-change-request"}


def register_cli_commands(subparsers) -> None:
    """Register all CLI command subparsers."""

    subparsers.add_parser("status", help="Show integration status")

    ns_parser = subparsers.add_parser("next-scope", help="Get the next scope")
    ns_parser.add_argument(
        "--full", action="store_true", default=False,
        help="Force full scope tree (default: auto mode with smart expand)",
    )

    ut_parser = subparsers.add_parser("update-tasks", help="Update task statuses")
    ut_parser.add_argument(
        "operations", help='JSON array of task operations, e.g. \'[{"task_designator":"T-1","updated_status":"Done"}]\'',
    )

    scr_parser = subparsers.add_parser("submit-change-request", help="Submit a document change request")
    scr_parser.add_argument("--message", "-m", required=True, help="What needs to change and why")
    scr_parser.add_argument("--designators", "-d", nargs="+", required=True, help="Document designators")
    scr_parser.add_argument("--session-id", default=None, help="Existing session ID to submit into")
    scr_parser.add_argument("--name", default=None, help="Session title when creating a new session")
    scr_parser.add_argument("--project-id", default=None, help="Override project ID from config")


def _render_response(title: str, response, fmt: MCPOutputFormat) -> str:
    """Render a response model for CLI output."""
    dumped = response.model_dump(exclude_none=True)
    if fmt == MCPOutputFormat.MD_YAML:
        return format_response_as_markdown(title, dumped)
    return json.dumps(dumped, indent=4)


async def run_cli_command(command: str, args, config_service) -> None:
    """Dispatch a CLI command to its handler and print formatted output."""
    from .commands import (
        mcp_handle_status,
        mcp_handle_next_scope,
        mcp_handle_update_tasks,
        mcp_handle_submit_change_request,
    )

    fmt = config_service.config.response_format

    if command == "status":
        response = await mcp_handle_status()
        print(_render_response("Status", response, fmt))

    elif command == "next-scope":
        response = await mcp_handle_next_scope(full=args.full)
        if fmt == MCPOutputFormat.MD_YAML and response.success and response.data:
            print(format_response_as_markdown("Next Scope", response.data))
        else:
            print(_render_response("Next Scope", response, fmt))

    elif command == "update-tasks":
        operations = json.loads(args.operations)
        response = await mcp_handle_update_tasks(operations)
        if fmt == MCPOutputFormat.MD_YAML:
            print(response.render_as_markdown_yaml())
        else:
            print(json.dumps(response.model_dump(exclude_none=True), indent=4))

    elif command == "submit-change-request":
        response = await mcp_handle_submit_change_request(
            args.message, args.designators,
            session_id=args.session_id, name=args.name,
            project_id=args.project_id,
        )
        print(_render_response("Change Request", response, fmt))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the Nautex CLI."""
    parser = argparse.ArgumentParser(
        prog="nautex",
        description="nautex - Nautex AI platform MCP integration tool and server",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # TUI setup command (also supports non-interactive mode via --token etc.)
    setup_parser = subparsers.add_parser("setup", help="Interactive setup configuration")
    setup_parser.add_argument("--token", "-t", default=None, help="API token")
    setup_parser.add_argument("--project", "-p", default=None, help="Project ID")
    setup_parser.add_argument("--plan", "-l", default=None, help="Implementation plan ID")
    setup_parser.add_argument("--agent", "-a", default=None,
                              choices=["claude", "cursor", "codex", "opencode", "gemini"],
                              help="Agent type")
    setup_parser.add_argument("--host", default=None,
                              help="Override API host URL (saved to .nautex/.env)")
    setup_parser.add_argument("--yes", "-y", action="store_true", default=False,
                              help="Skip all confirmations")

    # MCP server command
    subparsers.add_parser("mcp", help="Start MCP server for IDE integration")

    # Gateway node daemon
    gw_parser = subparsers.add_parser("gateway", help="[Experimental] Run local daemon that bridges coding agents to Nautex cloud")
    gw_subparsers = gw_parser.add_subparsers(dest="gateway_command")

    # gateway setup --token <TOKEN>
    gw_setup_parser = gw_subparsers.add_parser("setup", help="Save gateway access token to .nautex/.env")
    gw_setup_parser.add_argument("--token", required=True, help="API token for gateway authentication")
    gw_setup_parser.add_argument("--host", default=None, help="Override API host URL")

    # gateway [run] (default — start the daemon)
    gw_parser.add_argument("--uplink-url", default=None,
                           help="Backend WebSocket URL (derived from config api_host if omitted)")
    gw_parser.add_argument("--auth-token", default=None,
                           help="Bearer token for WS auth (read from config api_token if omitted)")
    gw_parser.add_argument("--directory-scope", default=".",
                           help="Working directory scope for agents")
    gw_parser.add_argument("--headless", action="store_true", default=True,
                           help="Run without TUI (default)")

    # Register all API commands (status, next-scope, update-tasks, submit-change-request)
    register_cli_commands(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # Base services
    config_service = ConfigurationService()
    config_service.load_configuration()

    if args.command == "gateway":
        gateway_cmd = getattr(args, 'gateway_command', None)

        if gateway_cmd == "setup":
            config_service.save_token_to_nautex_env(args.token)
            print(f"Gateway token saved to .nautex/.env")
            if args.host:
                config_service.save_to_nautex_env('API_HOST', args.host)
                print(f"API host saved to .nautex/.env")
            print("\nNext step: run `nautex gateway` to start the daemon.")
            return

        # Default: run the gateway daemon
        import logging as _logging
        _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        from .gateway.gateway_node_service import GatewayNodeService
        from .gateway.config import GatewayNodeConfig

        # Resolve auth token: CLI arg > config api_token
        auth_token = args.auth_token or config_service.config.get_token()
        if not auth_token:
            print("Error: No auth token. Run `nautex gateway setup --token <TOKEN>` first, or pass --auth-token.", file=sys.stderr)
            sys.exit(1)

        # Resolve uplink URL: CLI arg > derived from config api_host
        uplink_url = args.uplink_url or _derive_ws_url(config_service.config.api_host)

        directory_scope = os.path.abspath(args.directory_scope)
        config = GatewayNodeConfig(
            directory_scope=directory_scope,
            headless_mode=args.headless,
            uplink_url=uplink_url,
            auth_token=auth_token,
            node_instance_id="node-" + uuid.uuid4().hex[:12],
        )
        asyncio.run(GatewayNodeService(config).start())
        return

    elif args.command == "setup":
        has_cli_args = any([args.token, args.project, args.plan, args.agent])
        if has_cli_args:
            from .setup_noninteractive import run_noninteractive_setup
            asyncio.run(run_noninteractive_setup(args, config_service))
        else:
            # Setup requires the full service stack for TUI
            mcp_config_service = MCPConfigService(config_service)
            agent_rules_service = AgentRulesService(config_service)
            api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
            nautex_api_service = NautexAPIService(api_client, config_service)
            integration_status_service = IntegrationStatusService(
                config_service=config_service,
                mcp_config_service=mcp_config_service,
                agent_rules_service=agent_rules_service,
                nautex_api_service=nautex_api_service,
            )
            ui_service = UIService(
                config_service=config_service,
                integration_status_service=integration_status_service,
                api_service=nautex_api_service,
                mcp_config_service=mcp_config_service,
                agent_rules_service=agent_rules_service,
            )
            asyncio.run(ui_service.handle_setup_command())

    elif args.command == "mcp":
        mcp_config_service = MCPConfigService(config_service)
        agent_rules_service = AgentRulesService(config_service)
        api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
        nautex_api_service = NautexAPIService(api_client, config_service)
        integration_status_service = IntegrationStatusService(
            config_service=config_service,
            mcp_config_service=mcp_config_service,
            agent_rules_service=agent_rules_service,
            nautex_api_service=nautex_api_service,
        )
        document_service = DocumentService(
            nautex_api_service=nautex_api_service,
            config_service=config_service,
        )
        try:
            init_mcp_services(
                config_service=config_service,
                integration_status_service=integration_status_service,
                nautex_api_service=nautex_api_service,
                document_service=document_service,
            )
            mcp_server_run()
        except Exception as e:
            print(f"MCP server error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command in CLI_COMMANDS:
        # API commands: initialize MCP services then dispatch
        mcp_config_service = MCPConfigService(config_service)
        agent_rules_service = AgentRulesService(config_service)
        api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
        nautex_api_service = NautexAPIService(api_client, config_service)
        integration_status_service = IntegrationStatusService(
            config_service=config_service,
            mcp_config_service=mcp_config_service,
            agent_rules_service=agent_rules_service,
            nautex_api_service=nautex_api_service,
        )
        document_service = DocumentService(
            nautex_api_service=nautex_api_service,
            config_service=config_service,
        )
        init_mcp_services(
            config_service=config_service,
            integration_status_service=integration_status_service,
            nautex_api_service=nautex_api_service,
            document_service=document_service,
        )
        asyncio.run(run_cli_command(args.command, args, config_service))


if __name__ == "__main__":
    main()
