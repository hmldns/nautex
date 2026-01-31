"""Nautex API Service for business logic and model mapping."""

from typing import Optional, List, Dict, Any, Tuple
import logging
import asyncio
import aiohttp
from pydantic import SecretStr
import time

from . import ConfigurationService
from .nautex_api_protocol import NautexAPIProtocol
from ..api.client import NautexAPIClient, NautexAPIError
from ..api.api_models import (
    AccountInfo,
    Project,
    ImplementationPlan,
    Task,
    APIResponse, TaskOperation
)

# Set up logging
logger = logging.getLogger(__name__)


class NautexAPIService(NautexAPIProtocol):
    """Business logic layer for interacting with the Nautex.ai API."""

    def __init__(self, api_client: NautexAPIClient, config_service: ConfigurationService):
        """Initialize the API service.

        Args:
            api_client: The API client
            config: Application configuration containing API settings
        """
        self.api_client = api_client
        self.config_service = config_service
        self.api_client.setup_token(self.get_token)

        logger.debug("NautexAPIService initialized")

    def get_token(self):
        rv = self.config_service.config.get_token()
        return rv


    async def check_network_connectivity(self, timeout: float = 5.0) -> Tuple[bool, Optional[float], Optional[str]]:
        """Check network connectivity to the API host with short timeout.

        Args:
            timeout: Request timeout in seconds (default: 5.0)

        Returns:
            Tuple of (is_connected, response_time, error_message)
        """

        start_time = time.time()
        try:
            # Use get_account_info with the specified timeout to check connectivity
            await self.api_client.get_account_info(timeout=timeout, token_override="Not valid token for connection check")

            response_time = time.time() - start_time
            return True, response_time, None

        except NautexAPIError as e:
            response_time = time.time() - start_time
            # Even if we get an API error (like 401 unauthorized), it means network is reachable
            if e.status_code is not None and e.status_code < 500:
                return True, response_time, None
            else:
                return False, response_time, f"API error: {str(e)}"
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            return False, response_time, "Connection timeout"
        except aiohttp.ClientConnectorError as e:
            response_time = time.time() - start_time
            return False, response_time, f"Connection failed: {str(e)}"
        except Exception as e:
            response_time = time.time() - start_time
            return False, response_time, f"Network error: {str(e)}"

    # Latency properties

    @property
    def latency_stats(self) -> Dict[str, Tuple[float, float]]:
        """Get min/max latency statistics for all endpoint types.

        Returns:
            Dictionary mapping endpoint types to (min, max) latency tuples
        """
        return self.api_client.get_latency_stats()

    @property
    def api_latency(self) -> Tuple[float, float]:
        """Get min/max latency across all endpoint types.

        Returns:
            Tuple of (min_latency, max_latency) in seconds
        """
        stats = self.api_client.get_latency_stats()
        if not stats:
            return (0.0, 0.0)

        # Collect all latency measurements
        all_min_values = [min_val for min_val, _ in stats.values() if min_val > 0]
        all_max_values = [max_val for _, max_val in stats.values() if max_val > 0]

        # Calculate overall min/max
        if all_min_values and all_max_values:
            return (min(all_min_values), max(all_max_values))
        return (0.0, 0.0)

    # For backward compatibility
    @property
    def account_latency(self) -> Tuple[float, float]:
        """Get min/max latency across all endpoints (for backward compatibility).

        Returns:
            Tuple of (min_latency, max_latency) in seconds
        """
        return self.api_latency

    # API endpoint implementations


    async def get_account_info(self, *, token_override: Optional[str] = None, raise_exception: bool = True, timeout: Optional[float] = None) -> Optional[AccountInfo]:
        """Retrieve account information using the current token.

        Returns:
            Account information

        Raises:
            NautexAPIError: If token is invalid or API call fails
        """
        try:
            return await self.api_client.get_account_info(token_override=token_override, timeout=timeout)
        except NautexAPIError as e:
            if raise_exception:
                raise
            return None

    async def verify_token_and_get_account_info(self, token: Optional[str] = None) -> AccountInfo:
        # TODO update
        """Verify API token and retrieve account information.

        This method is maintained for backward compatibility.
        New code should use verify_token() and get_account_info() separately.

        Args:
            token: API token to verify (uses config token if not provided)

        Returns:
            Account information

        Raises:
            NautexAPIError: If token is invalid or API call fails
        """
        if token:
            # Temporarily set the token for verification
            original_token = self.api_client._token
            self.api_client.setup_token(token)

            try:
                account_info = await self.api_client.get_account_info()

                # If verification succeeded, update config with the new token
                self.config.api_token = SecretStr(token)

                return account_info
            except Exception:
                # Restore original token if verification failed
                self.api_client.setup_token(original_token)
                raise
        else:
            # Use the current token
            return await self.api_client.get_account_info()

    async def list_projects(self) -> List[Project]:
        """List all projects available to the user.

        Returns:
            List of projects

        Raises:
            NautexAPIError: If API call fails
        """
        try:
            return await self.api_client.list_projects()
        except NautexAPIError as e:
            logger.error(f"Failed to list projects: {e}")
            raise

    async def list_implementation_plans(self, project_id: str, from_mcp: bool = False) -> List[ImplementationPlan]:
        """List implementation plans for a specific project.

        Args:
            project_id: ID of the project
            from_mcp: Whether the request is coming from MCP

        Returns:
            List of implementation plans

        Raises:
            NautexAPIError: If API call fails
        """
        try:
            return await self.api_client.list_implementation_plans(project_id, from_mcp=from_mcp)
        except NautexAPIError as e:
            logger.error(f"Failed to list implementation plans for project {project_id}: {e}")
            raise

    async def next_scope(self, project_id: str, plan_id: str, from_mcp: bool = False) -> Optional["ScopeContext"]:
        """Get the next scope for a specific project and plan.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            from_mcp: Whether the request is coming from MCP

        Returns:
            A ScopeContext object containing the next scope information, or None if no scope is available

        Raises:
            NautexAPIError: If API call fails
        """

        try:
            return await self.api_client.get_next_scope(project_id, plan_id, from_mcp=from_mcp)
        except NautexAPIError as e:
            logger.error(f"Failed to get next scope for project {project_id}, plan {plan_id}: {e}")
            raise

    async def update_tasks(self, project_id: str, plan_id: str, operations: List["TaskOperation"], from_mcp: bool = False) -> APIResponse:
        """Update multiple tasks in a batch operation.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            operations: List of TaskOperation objects, each containing:
                - task_designator: The designator of the task to update
                - updated_status: Optional new status for the task
                - new_note: Optional new note to add to the task
            from_mcp: Whether the request is coming from MCP

        Returns:
            API response containing the results of the operations

        Raises:
            NautexAPIError: If API call fails
        """

        try:
            response_data = await self.api_client.update_tasks_batch(project_id, plan_id, operations, from_mcp=from_mcp)
            return APIResponse.model_validate(response_data)
        except NautexAPIError as e:
            logger.error(f"Failed to execute batch task update: {e}")
            raise

    async def get_implementation_plan(self, project_id: str, plan_id: str, from_mcp: bool = False) -> Optional["ImplementationPlan"]:
        """Get a specific implementation plan by plan_id.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            from_mcp: Whether the request is coming from MCP

        Returns:
            An ImplementationPlan object containing the plan details, or None if the plan was not found

        Raises:
            NautexAPIError: If API call fails
        """

        try:
            return await self.api_client.get_implementation_plan(project_id, plan_id, from_mcp=from_mcp)
        except NautexAPIError as e:
            logger.error(f"Failed to get implementation plan {plan_id} for project {project_id}: {e}")
            raise

    async def get_document_tree(self, project_id: str, doc_designator: str, from_mcp: bool = False) -> Optional["Document"]:
        """Get a document tree by designator.

        Args:
            project_id: The ID of the project
            doc_designator: The designator of the document
            from_mcp: Whether the request is coming from MCP

        Returns:
            A Document object containing the document tree, or None if the document was not found

        Raises:
            NautexAPIError: If API call fails
        """

        try:
            return await self.api_client.get_document_tree(project_id, doc_designator, from_mcp=from_mcp)
        except NautexAPIError as e:
            logger.error(f"Failed to get document tree for {doc_designator} in project {project_id}: {e}")
            raise
