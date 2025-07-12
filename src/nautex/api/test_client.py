"""Test client for emulating successful API responses during development."""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

# Set up logging
logger = logging.getLogger(__name__)


class NautexTestAPIClient:
    """Test API client that emulates successful responses from Nautex.ai API.

    This client provides dummy responses for all API endpoints to enable
    development and testing without requiring actual API connectivity.
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        """Initialize the test API client.

        Args:
            base_url: Base URL (ignored in test mode, but maintained for interface compatibility)
        """
        self.base_url = base_url.rstrip('/')
        self._token = None

        # Simulated latency tracking
        self._latency_measurements = {
            "account": [],
            "projects": [],
            "plans": [],
            "tasks": [],
            "requirements": []
        }

        logger.info("NautexTestAPIClient initialized in test mode")

    def setup_token(self, token: str) -> None:
        """Set up the API token for authentication.

        Args:
            token: API token string
        """
        self._token = token
        logger.debug("API token configured in test mode")

    def get_latency_stats(self, endpoint_type: Optional[str] = None) -> Dict[str, Tuple[float, float]]:
        """Get min/max latency statistics for endpoint types.

        Args:
            endpoint_type: Specific endpoint type to get stats for, or None for all

        Returns:
            Dictionary mapping endpoint types to (min, max) latency tuples
        """
        stats = {}

        for ep_type, measurements in self._latency_measurements.items():
            if measurements:
                stats[ep_type] = (min(measurements), max(measurements))
            else:
                stats[ep_type] = (0.0, 0.0)

        if endpoint_type:
            return {endpoint_type: stats.get(endpoint_type, (0.0, 0.0))}

        return stats

    async def verify_token(self) -> bool:
        """Verify if the current token is valid.

        Returns:
            Always True in test mode
        """
        await self._simulate_network_delay()
        return True

    async def get_account_info(self, timeout: Optional[float] = None) -> ():
        """Get account information.

        Returns:
            AccountInfo object with test data
        """
        await self._simulate_network_delay()

        # Record latency
        self._latency_measurements["account"].append(0.123)

        # Return test account info
        from .api_models import AccountInfo
        return AccountInfo(
            profile_email="test.user@example.com",
            api_version="1.0.0"
        )

    async def list_projects(self):
        """List projects.

        Returns:
            List of Project objects with test data
        """
        await self._simulate_network_delay()

        # Record latency
        self._latency_measurements["projects"].append(0.156)

        from .api_models import Project
        return [
            Project(
                id="PROJ-001",
                name="Test Project Alpha",
                description="Sample project for development testing"
            ),
            Project(
                id="PROJ-002", 
                name="Demo Project Beta",
                description="Another sample project for testing"
            )
        ]

    async def list_implementation_plans(self, project_id: str):
        """List implementation plans for a project.

        Args:
            project_id: Project ID

        Returns:
            List of ImplementationPlan objects with test data
        """
        await self._simulate_network_delay()

        # Record latency
        self._latency_measurements["plans"].append(0.189)

        from .api_models import ImplementationPlan
        return [
            ImplementationPlan(
                id="PLAN-001",
                project_id=project_id,
                name="Initial Implementation",
                description="First phase implementation plan"
            )
        ]

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self):
        """Close method for interface compatibility."""
        logger.debug("NautexTestAPIClient closed")

    async def _simulate_network_delay(self, min_ms: int = 50, max_ms: int = 200):
        """Simulate realistic network delay for testing."""
        import random
        delay = random.randint(min_ms, max_ms) / 1000.0
        await asyncio.sleep(delay)

    async def get(self, endpoint_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        """Make a simulated GET request.

        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers (analyzed to determine response type)

        Returns:
            Dummy JSON response based on endpoint
        """
        await self._simulate_network_delay()

        logger.debug(f"Test API GET request to: {endpoint_url}")

        # Parse endpoint to determine what dummy data to return
        if "/d/v1/account" in endpoint_url:
            return self._get_account_info_response()
        elif "/d/v1/projects" in endpoint_url:
            return self._get_projects_response()
        elif "/d/v1/implementation-plans" in endpoint_url:
            return self._get_implementation_plans_response()
        elif "/d/v1/agents" in endpoint_url:
            return self._get_agents_response()
        else:
            return self._get_generic_success_response()

    async def post(
        self, 
        endpoint_url: str, 
        headers: Dict[str, str], 
        json_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make a simulated POST request.

        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers
            json_payload: JSON request body

        Returns:
            Dummy JSON response based on endpoint and payload
        """
        await self._simulate_network_delay(100, 300)  # POST requests typically take longer

        logger.debug(f"Test API POST request to: {endpoint_url} with payload: {json_payload}")

        # Parse endpoint to determine what dummy data to return
        if "/d/v1/agents" in endpoint_url:
            return self._post_agent_response(json_payload)
        elif "/d/v1/projects" in endpoint_url:
            return self._post_project_response(json_payload)
        elif "/d/v1/implementation-plans" in endpoint_url:
            return self._post_implementation_plan_response(json_payload)
        else:
            return self._get_generic_success_response()

    def _get_account_info_response(self) -> Dict[str, Any]:
        """Generate dummy account info response."""
        return {
            "profile_email": "test.user@example.com",
            "api_version": "1.0.0",
            "response_latency": 0.123
        }

    def _get_projects_response(self) -> Dict[str, Any]:
        """Generate dummy projects list response."""
        return {
            "success": True,
            "data": [
                {
                    "id": "PROJ-001",
                    "name": "Test Project Alpha",
                    "description": "Sample project for development testing",
                    "status": "active",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-20T14:45:00Z"
                },
                {
                    "id": "PROJ-002", 
                    "name": "Demo Project Beta",
                    "description": "Another sample project for testing",
                    "status": "active",
                    "created_at": "2024-01-18T09:15:00Z",
                    "updated_at": "2024-01-22T16:20:00Z"
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_count": 2
        }

    def _get_implementation_plans_response(self) -> Dict[str, Any]:
        """Generate dummy implementation plans response."""
        return {
            "success": True,
            "data": [
                {
                    "id": "PLAN-001",
                    "project_id": "PROJ-001",
                    "name": "Initial Implementation",
                    "description": "First phase implementation plan",
                    "status": "active",
                    "phases": [
                        {
                            "id": "PHASE-001",
                            "name": "Setup & Configuration",
                            "status": "completed"
                        },
                        {
                            "id": "PHASE-002", 
                            "name": "Core Development",
                            "status": "in_progress"
                        }
                    ],
                    "created_at": "2024-01-16T11:00:00Z",
                    "updated_at": "2024-01-21T15:30:00Z"
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_count": 1
        }

    def _get_agents_response(self) -> Dict[str, Any]:
        """Generate dummy agents list response."""
        return {
            "success": True,
            "data": [
                {
                    "id": "AGENT-001",
                    "name": "test-dev-agent",
                    "project_id": "PROJ-001",
                    "implementation_plan_id": "PLAN-001",
                    "status": "active",
                    "last_activity": "2024-01-23T12:00:00Z",
                    "created_at": "2024-01-16T11:30:00Z"
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_count": 1
        }

    def _post_agent_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate dummy agent creation response."""
        agent_name = payload.get("name", "new-agent")
        return {
            "success": True,
            "data": {
                "id": f"AGENT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "name": agent_name,
                "project_id": payload.get("project_id"),
                "implementation_plan_id": payload.get("implementation_plan_id"),
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _post_project_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate dummy project creation response."""
        project_name = payload.get("name", "New Project")
        return {
            "success": True,
            "data": {
                "id": f"PROJ-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "name": project_name,
                "description": payload.get("description", ""),
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _post_implementation_plan_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate dummy implementation plan creation response."""
        plan_name = payload.get("name", "New Implementation Plan")
        return {
            "success": True,
            "data": {
                "id": f"PLAN-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "project_id": payload.get("project_id"),
                "name": plan_name,
                "description": payload.get("description", ""),
                "status": "active",
                "phases": [],
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _get_generic_success_response(self) -> Dict[str, Any]:
        """Generate a generic successful response."""
        return {
            "success": True,
            "data": {"message": "Operation completed successfully"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        } 
