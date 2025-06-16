#!/usr/bin/env python3

import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

# Add src directory to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from src.nautex.tui.screens.status_screen import StatusScreen
from src.nautex.services.integration_status_service import IntegrationStatus, IntegrationStatusService
from src.nautex.services.mcp_config_service import MCPConfigStatus


# --- MOCK INTEGRATION STATUS SERVICE ---
class MockIntegrationStatusService:
    """Mock integration status service for testing."""

    async def get_integration_status(self) -> IntegrationStatus:
        """Return mock integration status."""
        # Simulate some delay like a real API call
        await asyncio.sleep(0.2)

        return IntegrationStatus(
            config_loaded=True,
            config_path=Path("/home/user/dev/phoenix-ui/nautex.toml"),
            config_summary={
                'agent_instance_name': 'phoenix-ui-dev',
                'project_id': 'proj_phoenix_ui_2024',
                'implementation_plan_id': 'plan_mvp_components',
                'has_token': True,
            },
            api_connected=True,
            api_response_time=0.156,
            account_info=None,
            mcp_status=MCPConfigStatus.OK,
            mcp_config_path=Path("/home/user/dev/phoenix-ui/.cursor/mcp.json"),
            integration_ready=True,
            status_message="All systems operational - ready for development"
        )

# --- MOCK DATA AND MODELS ---
mock_task = SimpleNamespace(
    task_designator="T2.3",
    name="Implement User Authentication Modal",
    description="Create a reusable authentication modal with email/password validation, loading states, and error handling. Should integrate with the existing auth service.",
    status="pending"
)

mock_plan_context = SimpleNamespace(
    config_summary={
        'agent_instance_name': 'phoenix-ui-dev',
        'project_id': 'proj_phoenix_ui_2024',
        'implementation_plan_id': 'plan_mvp_components',
        'has_token': True,
    },
    mcp_status=SimpleNamespace(value="OK"),
    mcp_config_path="/home/user/dev/phoenix-ui/.cursor/mcp.json",
    next_task=mock_task,
    advised_action="Run `nautex workon T2.3` to begin implementing the authentication modal.",
    config_loaded=True,
    config_path="/home/user/dev/phoenix-ui/nautex.toml",
    api_connected=True,
    api_response_time=0.156,
    account_info=None,
    timestamp="2024-12-19T14:30:00Z",
)

class SampleStatusApp(StatusScreen):
    """A sample app to run the StatusScreen with mock data."""

    def __init__(self):
        mock_integration_service = MockIntegrationStatusService()
        super().__init__(
            plan_context=mock_plan_context,
            integration_status_service=mock_integration_service,
        )

    def on_mount(self) -> None:
        """Override to add debug info."""
        self.sub_title = "🧪 Debug Mode - Mock Data"
        return super().on_mount()

if __name__ == "__main__":
    print("🚀 Starting Nautex Status Screen Debug Mode...")
    print("📋 This will show a mock status screen with sample data")
    print("🎮 Controls: Press 'q', 'Ctrl+C', or 'Escape' to quit")
    print("─" * 50)

    try:
        app = SampleStatusApp()
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Debug session ended by user")
    except Exception as e:
        print(f"\n❌ Error running debug screen: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🏁 Debug session complete") 
