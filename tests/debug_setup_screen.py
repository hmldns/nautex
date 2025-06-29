#!/usr/bin/env python3

import sys
import asyncio
from pathlib import Path
from typing import List, Optional, Tuple

# Add src directory to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.nautex.tui.screens.setup_screen import SetupScreen, SetupApp
from src.nautex.services.config_service import ConfigurationService
from src.nautex.models.integration_status import IntegrationStatus
from src.nautex.services.mcp_config_service import MCPConfigService, MCPConfigStatus
from src.nautex.api.api_models import Project, ImplementationPlan, AccountInfo
from src.nautex.models.config_models import NautexConfig
from pydantic import SecretStr

# --- MOCK CONFIGURATION SERVICE ---
class MockConfigurationService:
    """Mock configuration service for testing."""

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize with optional project root."""
        self.project_root = project_root or Path.cwd()
        self.config_data = None

    def load_configuration(self) -> NautexConfig:
        """Return mock configuration."""
        if self.config_data:
            return self.config_data
        return NautexConfig(
            agent_instance_name="debug-agent",
            api_token=SecretStr("mock-api-token"),
            project_id="mock-project-id",
            plan_id="mock-plan-id"
        )

    def save_configuration(self, config_data: NautexConfig) -> None:
        """Save configuration (mock)."""
        self.config_data = config_data
        print(f"✅ Configuration saved (mock): {config_data}")

    def config_exists(self) -> bool:
        """Check if config exists (mock)."""
        return self.config_data is not None

    def get_config_path(self) -> Path:
        """Get path to config file (mock)."""
        return self.project_root / "nautex.toml"

# --- MOCK INTEGRATION STATUS SERVICE ---
class MockIntegrationStatusService:
    """Mock integration status service for testing."""

    def __init__(
        self,
        config_service: ConfigurationService,
        mcp_config_service: MCPConfigService,
        project_root: Optional[Path] = None
    ):
        """Initialize with required services."""
        self.config_service = config_service
        self.mcp_config_service = mcp_config_service
        self.project_root = project_root or Path.cwd()

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

    async def validate_api_token(self, token: str) -> Tuple[bool, Optional[AccountInfo], Optional[str]]:
        """Validate API token (mock)."""
        # Simulate some delay like a real API call
        await asyncio.sleep(0.5)

        if token and len(token) > 8:
            account_info = AccountInfo(
                profile_email="user@example.com",
                api_version="1.0.0",
                account_id="acc_12345",
                organization_id="org_67890"
            )
            return True, account_info, None
        else:
            return False, None, "Invalid token format"

# --- MOCK NAUTEX API SERVICE ---
class MockNautexAPIService:
    """Mock Nautex API service for testing."""

    def __init__(self, api_client=None, config=None):
        """Initialize with optional API client and config."""
        self.api_client = api_client
        self.config = config
        self._api_latency = (0.1, 0.2)  # min, max latency

    @property
    def api_latency(self) -> Tuple[float, float]:
        """Get API latency information."""
        return self._api_latency

    async def verify_token_and_get_account_info(self, token: Optional[str] = None) -> AccountInfo:
        """Verify token and get account info (mock)."""
        await asyncio.sleep(0.3)
        return AccountInfo(
            profile_email="user@example.com",
            api_version="1.0.0",
            account_id="acc_12345",
            organization_id="org_67890"
        )

    async def list_projects(self) -> List[Project]:
        """List available projects (mock)."""
        await asyncio.sleep(0.3)
        return [
            Project(
                project_id="proj_1",
                name="E-commerce Platform",
                description="Full-stack e-commerce web application"
            ),
            Project(
                project_id="proj_2",
                name="CRM System",
                description="Customer relationship management system"
            ),
            Project(
                project_id="proj_3",
                name="Mobile App",
                description="Cross-platform mobile application"
            )
        ]

    async def list_implementation_plans(self, project_id: str) -> List[ImplementationPlan]:
        """List implementation plans for a project (mock)."""
        await asyncio.sleep(0.3)
        return [
            ImplementationPlan(
                plan_id="plan_1",
                project_id=project_id,
                name="MVP Development",
                description="Minimum viable product implementation"
            ),
            ImplementationPlan(
                plan_id="plan_2",
                project_id=project_id,
                name="Feature Expansion",
                description="Adding additional features to the base product"
            ),
            ImplementationPlan(
                plan_id="plan_3",
                project_id=project_id,
                name="Performance Optimization",
                description="Optimizing performance and scalability"
            )
        ]

# --- MOCK MCP CONFIG SERVICE ---
class MockMCPConfigService:
    """Mock MCP config service for testing."""

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize with optional project root."""
        self.project_root = project_root or Path.cwd()

    def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check MCP configuration status (mock)."""
        return MCPConfigStatus.OK, self.project_root / ".cursor" / "mcp.json"

# --- SAMPLE SETUP APP ---
class SampleSetupApp(SetupApp):
    """A sample app to run the SetupScreen with mock data."""

    def __init__(self):
        # Create mock services
        self.config_service = MockConfigurationService()
        self.project_root = Path.cwd()
        super().__init__(
            config_service=self.config_service,
            project_root=self.project_root
        )

    def on_mount(self) -> None:
        """Override to use mock services."""
        mcp_config_service = MockMCPConfigService(self.project_root)
        integration_status_service = MockIntegrationStatusService(
            config_service=self.config_service,
            mcp_config_service=mcp_config_service,
            project_root=self.project_root
        )

        # Create a mock API service
        api_service = MockNautexAPIService()

        # Create and push the setup screen with mock services
        setup_screen = SetupScreen(
            config_service=self.config_service,
            project_root=self.project_root,
            integration_status_service=integration_status_service,
            api_service=api_service
        )

        # Add debug indicator
        setup_screen.sub_title = "🧪 Debug Mode - Mock Data"

        self.push_screen(setup_screen)

if __name__ == "__main__":
    print("🚀 Starting Nautex Setup Screen Debug Mode...")
    print("📋 This will show a mock setup screen with sample data")
    print("🎮 Controls: Press 'Ctrl+C' or 'Escape' to quit, 'Ctrl+S' to save")
    print("─" * 50)

    try:
        app = SampleSetupApp()
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Debug session ended by user")
    except Exception as e:
        print(f"\n❌ Error running debug screen: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🏁 Debug session complete")
