"""Nautex API Client for low-level HTTP communication."""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Tuple, Callable
import aiohttp
import json
from urllib.parse import urljoin

from .api_models import (
    AccountInfo,
    Project,
    ImplementationPlan,
    Task,
    APIResponse,
    TaskOperationRequest,
    Document
)
from .scope_context_model import ScopeContext

# Set up logging
logger = logging.getLogger(__name__)


class NautexAPIError(Exception):
    """Custom exception for Nautex API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        """Initialize with error details.

        Args:
            message: Error message
            status_code: HTTP status code if applicable
            response_body: Response body content if available
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class NautexAPIClient:
    """Asynchronous HTTP client for Nautex.ai API with endpoint-specific methods."""

    # API endpoint constants
    ENDPOINT_ACCOUNT = "account"
    ENDPOINT_PROJECTS = "projects"
    ENDPOINT_PLANS = "plans"
    ENDPOINT_TASKS = "tasks"
    ENDPOINT_REQUIREMENTS = "requirements"

    def __init__(self, base_url: str, token: Optional[str] = None):
        """Initialize the API client.

        Args:
            base_url: Base URL for the Nautex.ai API
            token: API token for authentication (can be set later with setup_token)
        """
        self.base_url = base_url.rstrip('/')
        self.api_version_path = "/d/v1/"
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None

        # Latency tracking per endpoint type
        self._latency_measurements: Dict[str, List[float]] = {
            self.ENDPOINT_ACCOUNT: [],
            self.ENDPOINT_PROJECTS: [],
            self.ENDPOINT_PLANS: [],
            self.ENDPOINT_TASKS: [],
            self.ENDPOINT_REQUIREMENTS: []
        }

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self, custom_timeout: Optional[float] = None):
        """Ensure aiohttp session is created.

        Args:
            custom_timeout: Optional custom timeout in seconds
        """
        if self._session is None or self._session.closed:
            if custom_timeout is not None:
                timeout = aiohttp.ClientTimeout(total=custom_timeout, connect=min(custom_timeout/2, 10))
            else:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={'Content-Type': 'application/json'}
            )

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self, 
        method: str, 
        endpoint_url: str, 
        headers: Optional[Dict[str, str]] = None, 
        json_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint_url: Full endpoint URL
            headers: Request headers
            json_payload: JSON request body
            timeout: Optional custom timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            NautexAPIError: For API errors
        """
        await self._ensure_session(timeout)

        # Merge headers
        request_headers = {}
        if headers:
            request_headers.update(headers)

        # Retry configuration
        max_retries = 3
        retry_delays = [1, 2, 4]  # Exponential backoff in seconds

        last_exception = None
        endpoint_type = self._get_endpoint_type(endpoint_url)

        for attempt in range(max_retries):
            try:
                logger.debug(f"API request attempt {attempt + 1}/{max_retries}: {method} {endpoint_url}")

                # Prepare request kwargs
                request_kwargs = {
                    'method': method,
                    'url': endpoint_url,
                    'headers': request_headers
                }

                if json_payload is not None:
                    request_kwargs['json'] = json_payload

                # Start timing the request
                start_time = time.time()

                async with self._session.request(**request_kwargs) as response:
                    response_text = await response.text()

                    # Calculate and record latency if request was successful
                    if 200 <= response.status < 300:
                        latency = time.time() - start_time
                        self._latency_measurements[endpoint_type].append(latency)
                        logger.debug(f"Request latency for {endpoint_type}: {latency:.3f}s")

                        try:
                            return await response.json()
                        except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                            logger.error(f"Failed to parse JSON response: {e}")
                            raise NautexAPIError(
                                f"Invalid JSON response: {str(e)}", 
                                status_code=response.status,
                                response_body=response_text
                            )

                    # Handle client errors (4xx) - don't retry
                    elif 400 <= response.status < 500:
                        # logger.error(f"Client error {response.status}: {response_text}")
                        raise NautexAPIError(
                            f"Client error {response.status}: {response_text}",
                            status_code=response.status,
                            response_body=response_text
                        )

                    # Handle server errors (5xx) - retry these
                    elif response.status >= 500:
                        error_msg = f"Server error {response.status}: {response_text}"
                        logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")
                        last_exception = NautexAPIError(
                            error_msg,
                            status_code=response.status,
                            response_body=response_text
                        )

                        # Don't sleep after the last attempt
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delays[attempt])
                        continue

                    else:
                        # Unexpected status code
                        error_msg = f"Unexpected response status {response.status}: {response_text}"
                        logger.error(error_msg)
                        raise NautexAPIError(
                            error_msg,
                            status_code=response.status,
                            response_body=response_text
                        )

            except aiohttp.ClientError as e:
                # Network-level errors - retry these
                error_msg = f"Network error: {str(e)}"
                logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")
                last_exception = NautexAPIError(f"Network error after {max_retries} attempts: {str(e)}")

                # Don't sleep after the last attempt
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])
                continue

            except NautexAPIError:
                # Re-raise our own exceptions (4xx errors, JSON parsing errors, etc.)
                raise

            except Exception as e:
                # Unexpected errors - don't retry
                logger.error(f"Unexpected error: {str(e)}")
                raise NautexAPIError(f"Unexpected error: {str(e)}")

        # If we get here, all retries failed
        if last_exception:
            raise last_exception
        else:
            raise NautexAPIError(f"Request failed after {max_retries} attempts")

    async def get(self, endpoint_url: str, headers: Dict[str, str], timeout: Optional[float] = None, from_mcp: bool = False) -> APIResponse:
        """Make a GET request.

        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers
            timeout: Optional custom timeout in seconds
            from_mcp: Whether the request is coming from MCP

        Returns:
            Parsed JSON response
        """
        # Add from_mcp query parameter if True
        if from_mcp:
            separator = "&" if "?" in endpoint_url else "?"
            endpoint_url += f"{separator}from_mcp=true"
            
        resp = await self._request("GET", endpoint_url, headers, timeout=timeout)
        return APIResponse(**resp)

    async def post(
        self, 
        endpoint_url: str, 
        headers: Dict[str, str], 
        json_payload: Dict[str, Any],
        from_mcp: bool = False
    ) -> Dict[str, Any]:
        """Make a POST request.

        Args:
            endpoint_url: Full endpoint URL
            headers: Request headers
            json_payload: JSON request body
            from_mcp: Whether the request is coming from MCP

        Returns:
            Parsed JSON response
        """
        # Add from_mcp query parameter if True
        if from_mcp:
            separator = "&" if "?" in endpoint_url else "?"
            endpoint_url += f"{separator}from_mcp=true"
            
        return await self._request("POST", endpoint_url, headers, json_payload)

    def setup_token(self, token: str | Callable[[], None]) -> None:
        """Set or update the API token.

        Args:
            token: API token for authentication
        """
        self._token = token
        logger.debug("API token updated")

    def _get_token(self):
        if callable(self._token):
            return self._token()
        else:
            return self._token

    def _get_auth_headers(self, token_override: Optional[str] = None) -> Dict[str, str]:
        """Get authentication headers for API requests.

        Returns:
            Dictionary containing Authorization header

        Raises:
            NautexAPIError: If no token is set
        """

        tkn = self._get_token() if not token_override else token_override

        if not tkn:
            raise NautexAPIError("No API token set. Call setup_token() first.")

        return {
            "Authorization": f"Bearer {tkn}"
        }

    def _get_full_api_url(self, endpoint_path: str) -> str:
        """Construct full API URL from endpoint path.

        Args:
            endpoint_path: API endpoint path (e.g., "projects", "tasks/123")

        Returns:
            Complete API URL
        """
        # Clean up endpoint path - remove leading slash if present
        endpoint_path = endpoint_path.lstrip('/')

        # Construct URL using urljoin for proper path handling
        base_with_version = urljoin(self.base_url, self.api_version_path)
        full_url = urljoin(base_with_version, endpoint_path)

        logger.debug(f"Constructed API URL: {full_url}")
        return full_url

    def _get_endpoint_type(self, url: str) -> str:
        """Determine the endpoint type from the URL.

        Args:
            url: The full endpoint URL

        Returns:
            The endpoint type (one of the ENDPOINT_* constants)
        """
        # Extract the endpoint type from the URL
        for endpoint_type in [
            self.ENDPOINT_ACCOUNT,
            self.ENDPOINT_PROJECTS,
            self.ENDPOINT_PLANS,
            self.ENDPOINT_TASKS,
            self.ENDPOINT_REQUIREMENTS
        ]:
            if f"/{endpoint_type}" in url or url.endswith(endpoint_type):
                return endpoint_type

        # Default to ENDPOINT_ACCOUNT if we can't determine the type
        return self.ENDPOINT_ACCOUNT

    def get_latency_stats(self, endpoint_type: Optional[str] = None) -> Dict[str, Tuple[float, float]]:
        """Get min/max latency statistics for the specified endpoint type or all endpoints.

        Args:
            endpoint_type: The endpoint type to get statistics for, or None for all endpoints

        Returns:
            Dictionary mapping endpoint types to (min, max) latency tuples
        """
        result = {}

        # Get stats for a specific endpoint type
        if endpoint_type is not None:
            measurements = self._latency_measurements.get(endpoint_type, [])
            if measurements:
                result[endpoint_type] = (min(measurements), max(measurements))
            else:
                result[endpoint_type] = (0.0, 0.0)
            return result

        # Get stats for all endpoint types
        for ep_type, measurements in self._latency_measurements.items():
            if measurements:
                result[ep_type] = (min(measurements), max(measurements))
            else:
                result[ep_type] = (0.0, 0.0)

        return result

    # API endpoint implementations

    async def verify_token(self, timeout: Optional[float] = None) -> bool:
        """Verify if the current API token is valid.

        Args:
            timeout: Optional custom timeout in seconds

        Returns:
            True if token is valid, False otherwise

        Raises:
            NautexAPIError: For unexpected API errors
        """
        try:
            await self.get_account_info(timeout=timeout)
            return True
        except NautexAPIError as e:
            if e.status_code == 401:
                logger.warning("Token verification failed: Invalid token")
                return False
            else:
                # Re-raise for unexpected errors
                raise

    async def get_account_info(self, *, token_override: Optional[str] = None, timeout: Optional[float] = None) -> AccountInfo:
        """Retrieve account information using the current token.

        Args:
            token_override: Optional token override to use instead of the current token (for token pre-validation)
            timeout: Optional custom timeout in seconds

        Returns:
            Account information

        Raises:
            NautexAPIError: If token is invalid or API call fails
        """
        headers = self._get_auth_headers(token_override=token_override)
        url = self._get_full_api_url(self.ENDPOINT_ACCOUNT)

        try:
            response = await self.get(url, headers, timeout=timeout)
            logger.debug("Successfully retrieved account information")

            acc_data = response.data.get('account')

            # Parse response into AccountInfo model
            return AccountInfo.model_validate(acc_data)

        except NautexAPIError as e:
            # logger.error(f"Failed to get account info: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_account_info: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def list_projects(self) -> List[Project]:
        """List all projects available to the user.

        Returns:
            List of projects

        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(self.ENDPOINT_PROJECTS)

        try:
            response = await self.get(url, headers)

            # Parse response into list of Project models
            projects_data = response.data.get('projects', [])
            return [Project.model_validate(project) for project in projects_data]

        except NautexAPIError as e:
            logger.error(f"Failed to list projects: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in list_projects: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

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
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}")

        try:
            response_data = await self.get(url, headers, from_mcp=from_mcp)

            # Parse response into list of ImplementationPlan models
            plans_data = response_data.data.get('plans', [])
            return [ImplementationPlan.model_validate(plan) for plan in plans_data]

        except NautexAPIError as e:
            logger.error(f"Failed to list implementation plans for project {project_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in list_implementation_plans: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def get_next_task(self, project_id: str, plan_id: str, from_mcp: bool = False) -> Optional[Task]:
        """Get the next available task for a project/plan.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            from_mcp: Whether the request is coming from MCP

        Returns:
            Next task or None if no tasks available

        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/{self.ENDPOINT_TASKS}/next")

        try:
            response_data = await self.get(url, headers, from_mcp=from_mcp)

            # Handle case where no task is available
            if not response_data or 'task' not in response_data:
                logger.debug(f"No next task available for project {project_id}, plan {plan_id}")
                return None

            task_data = response_data['task']
            if not task_data:
                return None

            logger.debug(f"Successfully retrieved next task for project {project_id}, plan {plan_id}")
            return Task.model_validate(task_data)

        except NautexAPIError as e:
            logger.error(f"Failed to get next task for project {project_id}, plan {plan_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_next_task: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def get_tasks_info(
        self, 
        project_id: str, 
        plan_id: str, 
        task_designators: List[str],
        from_mcp: bool = False
    ) -> List[Task]:
        """Get information for specific tasks.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designators: List of task identifiers
            from_mcp: Whether the request is coming from MCP

        Returns:
            List of tasks

        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/{self.ENDPOINT_TASKS}")

        # Create request payload
        request_data = {
            "task_designators": task_designators
        }

        try:
            response_data = await self.post(url, headers, request_data, from_mcp=from_mcp)
            logger.debug(f"Successfully retrieved {len(response_data.get('tasks', []))} tasks for project {project_id}, plan {plan_id}")

            # Parse response into list of Task models
            tasks_data = response_data.get('tasks', [])
            return [Task.model_validate(task) for task in tasks_data]

        except NautexAPIError as e:
            logger.error(f"Failed to get tasks info for project {project_id}, plan {plan_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_tasks_info: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def update_task_status(
        self, 
        project_id: str, 
        plan_id: str, 
        task_designator: str, 
        status: str,
        from_mcp: bool = False
    ) -> Task:
        """Update the status of a task.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designator: Task identifier
            status: New status for the task
            from_mcp: Whether the request is coming from MCP

        Returns:
            Updated task

        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/{self.ENDPOINT_TASKS}/{task_designator}/status")

        # Create request payload
        request_data = {
            "status": status
        }

        try:
            response_data = await self.post(url, headers, request_data, from_mcp=from_mcp)
            logger.debug(f"Successfully updated task {task_designator} status to {status}")

            # Parse response into Task model
            task_data = response_data.get('task', response_data)
            return Task.model_validate(task_data)

        except NautexAPIError as e:
            logger.error(f"Failed to update task {task_designator} status: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in update_task_status: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def add_task_note(
        self, 
        project_id: str, 
        plan_id: str, 
        task_designator: str, 
        content: str,
        from_mcp: bool = False
    ) -> Dict[str, Any]:
        """Add a note to a task.

        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designator: Task identifier
            content: Note content
            from_mcp: Whether the request is coming from MCP

        Returns:
            Confirmation dictionary

        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/{self.ENDPOINT_TASKS}/{task_designator}/notes")

        # Create request payload
        request_data = {
            "content": content
        }

        try:
            response_data = await self.post(url, headers, request_data, from_mcp=from_mcp)
            logger.debug(f"Successfully added note to task {task_designator}")

            # Return confirmation
            return {
                "task_designator": task_designator,
                "status": "note_added",
                "note_id": response_data.get("note_id"),
                "timestamp": response_data.get("timestamp")
            }

        except NautexAPIError as e:
            logger.error(f"Failed to add note to task {task_designator}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in add_task_note: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def update_tasks_batch(
        self, 
        project_id: str, 
        plan_id: str, 
        operations: List["TaskOperation"],
        from_mcp: bool = False
    ) -> Dict[str, Any]:
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

        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/tasks_update")

        # Create request payload
        request_data = TaskOperationRequest(operations=operations).model_dump()

        try:
            response_data = await self.post(url, headers, request_data, from_mcp=from_mcp)
            logger.debug(f"Successfully executed batch update for {len(operations)} tasks")

            # Return the API response
            return response_data

        except NautexAPIError as e:
            logger.error(f"Failed to execute batch task update: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in update_tasks_batch: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def get_document_tree(self, project_id: str, doc_designator: str, from_mcp: bool = False) -> Optional[Document]:
        """
        Get a document tree by designator.

        Args:
            project_id: The ID of the project
            doc_designator: The designator of the document
            from_mcp: Whether the request is coming from MCP

        Returns:
            A Document object containing the document tree, or None if the document was not found
        """

        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/documents/{doc_designator}/tree")

        try:
            response = await self.get(url, headers, from_mcp=from_mcp)

            # Handle APIResponse wrapper
            if response.status == "success" and response.data:
                document_data = response.data.get("document")
                if document_data:
                    return Document.model_validate(document_data)
                return None
            else:
                raise NautexAPIError(f"Unexpected response format: {response}")

        except NautexAPIError as e:
            if e.status_code == 404:
                # Document not found
                logger.debug(f"Document {doc_designator} not found for project {project_id}")
                return None
            logger.error(f"Failed to get document tree for {doc_designator}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_document_tree: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def get_implementation_plan(self, project_id: str, plan_id: str, from_mcp: bool = False) -> Optional[ImplementationPlan]:
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

        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}")

        try:
            response = await self.get(url, headers, from_mcp=from_mcp)

            # Handle APIResponse wrapper
            if response.status == "success" and response.data:
                plan_data = response.data.get("plan")
                if plan_data:
                    return ImplementationPlan.model_validate(plan_data)
                return None
            else:
                raise NautexAPIError(f"Unexpected response format: {response}")

        except NautexAPIError as e:
            if e.status_code == 404:
                # Plan not found
                logger.debug(f"Implementation plan {plan_id} not found for project {project_id}")
                return None
            logger.error(f"Failed to get implementation plan {plan_id} for project {project_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_implementation_plan: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")

    async def get_next_scope(self, project_id: str, plan_id: str, from_mcp: bool = False) -> Optional[ScopeContext]:
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

        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"{self.ENDPOINT_PROJECTS}/{project_id}/{self.ENDPOINT_PLANS}/{plan_id}/scope/next")

        try:
            response = await self.get(url, headers, from_mcp=from_mcp)

            # Handle case where no scope is available
            if not response.data or 'scope' not in response.data:
                logger.debug(f"No next scope available for project {project_id}, plan {plan_id}")
                return None

            scope_data = response.data.get('scope')
            if not scope_data:
                return None

            logger.debug(f"Successfully retrieved next scope for project {project_id}, plan {plan_id}")
            return ScopeContext.model_validate(scope_data)

        except NautexAPIError as e:
            if e.status_code == 404:
                # No next scope found
                logger.debug(f"No next scope available for project {project_id}, plan {plan_id}")
                return None
            logger.error(f"Failed to get next scope for project {project_id}, plan {plan_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_next_scope: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")
