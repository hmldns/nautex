"""Non-interactive setup mode for Nautex CLI.

Triggered when `nautex setup` is called with --token, --project, --plan, --agent flags.
Uses Rich for terminal output (transitive dependency of Textual, already available).
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from .models.config import AgentType, NautexConfig
from .services.config_service import ConfigurationService
from .api import create_api_client
from .services.nautex_api_service import NautexAPIService

console = Console()

AGENT_MAP = {
    "claude": AgentType.CLAUDE,
    "cursor": AgentType.CURSOR,
    "codex": AgentType.CODEX,
    "opencode": AgentType.OPENCODE,
    "gemini": AgentType.GEMINI,
}


async def run_noninteractive_setup(args, config_service: ConfigurationService) -> None:
    """Run non-interactive setup with all parameters provided via CLI args."""
    try:
        await _run_setup(args, config_service)
    except KeyboardInterrupt:
        console.print("\nAborted.")
        sys.exit(0)


async def _run_setup(args, config_service: ConfigurationService) -> None:
    # 1. Validate all 4 args are present
    missing = []
    if not args.token:
        missing.append("--token")
    if not args.project:
        missing.append("--project")
    if not args.plan:
        missing.append("--plan")
    if not args.agent:
        missing.append("--agent")

    if missing:
        console.print(f"[red]Error: Missing required arguments: {', '.join(missing)}[/red]")
        console.print("All four arguments are required for non-interactive setup:")
        console.print("  nautex setup --token TOKEN --project PROJECT_ID --plan PLAN_ID --agent AGENT")
        sys.exit(1)

    # 2. Map agent string to AgentType enum
    agent_type = AGENT_MAP[args.agent]

    # 3. Validate token, project, and plan against API before writing anything
    console.print("Validating...")
    api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
    api_service = NautexAPIService(api_client, config_service)

    try:
        # Validate token
        account_info = await api_service.get_account_info(token_override=args.token)
        console.print(f"  Token valid. Account: [green]{account_info.profile_email}[/green]")

        # Set token so subsequent API calls authenticate
        config_service._config = NautexConfig(api_token=args.token)

        # Validate project exists (silent=True to avoid triggering onboarding flags)
        project_name = None
        try:
            projects = await api_service.list_projects(silent=True)
            for p in projects:
                if p.project_id == args.project:
                    project_name = p.name
                    break
        except Exception:
            pass

        if not project_name:
            console.print(f"[red]Error: Project '{args.project}' not found in your account.[/red]")
            sys.exit(1)
        console.print(f"  Project: [green]{project_name}[/green]")

        # Validate plan exists (silent=True to avoid triggering onboarding flags)
        plan_name = None
        try:
            plan = await api_service.get_implementation_plan(args.project, args.plan, silent=True)
            if plan:
                plan_name = plan.name
        except Exception:
            pass

        if not plan_name:
            console.print(f"[red]Error: Plan '{args.plan}' not found in project '{project_name}'.[/red]")
            sys.exit(1)
        console.print(f"  Plan: [green]{plan_name}[/green]")

    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        sys.exit(1)
    finally:
        await api_client.close()

    # 4. Confirm working directory
    cwd = Path.cwd()
    console.print(f"\nWorking directory: [bold]{cwd}[/bold]")
    if not args.yes:
        if not Confirm.ask("Is this your project root?", default=True):
            console.print("Aborted. Run this command from your project root directory.")
            sys.exit(0)

    # 5. Check existing config
    if config_service.config_exists() and not args.yes:
        if not Confirm.ask("Existing config found. Overwrite?", default=True):
            console.print("Aborted.")
            sys.exit(0)

    # 6. Save config and token
    console.print("\nWriting configuration...")
    config_service._config = NautexConfig(
        project_id=args.project,
        plan_id=args.plan,
        agent_type=agent_type,
    )
    config_service.save_configuration()
    console.print("  Config saved to .nautex/config.json")

    config_service.save_token_to_nautex_env(args.token)
    console.print("  Token saved to .nautex/.env")

    # 7. Write MCP configuration
    console.print(f"\nConfiguring MCP for {agent_type.display_name()}...")
    agent_setup = config_service.agent_setup
    await agent_setup.write_mcp_configuration()
    console.print("  MCP configuration written")

    # 8. Write agent rules
    console.print("\nWriting agent rules...")
    agent_setup.ensure_rules()
    console.print("  Agent rules written")

    # 9. Signal backend that setup is done (non-silent to trigger onboarding flags)
    config_service.load_configuration()
    api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
    api_service = NautexAPIService(api_client, config_service)
    try:
        await api_service.get_implementation_plan(args.project, args.plan)
    except Exception:
        pass
    finally:
        await api_client.close()

    # 10. Print success panel
    console.print()
    panel_text = (
        f"Setup complete!\n"
        f"Agent: {agent_type.display_name()}\n"
        f"Project: {project_name}\n"
        f"Plan: {plan_name}\n"
        f"\n"
        f'Next: Tell your agent:\n'
        f'"Check nautex status"'
    )
    console.print(Panel.fit(panel_text, title="[green]Nautex Setup[/green]"))
