"""Nautex API Service for business logic and model mapping."""

from typing import Optional, List, Dict, Any
import logging
from urllib.parse import urljoin

from ..api.client import NautexAPIClient, NautexAPIError
from ..models.config_models import NautexConfig, AccountInfo
from ..models.api_models import (
    Project,
    ImplementationPlan,
    Task,
    Requirement,
    APIResponse,
    ProjectListRequest,
    PlanGetRequest,
    TaskActionRequest,
    RequirementActionRequest,
)

# Set up logging
logger = logging.getLogger(__name__)


class NautexAPIService:
    """Business logic layer for interacting with the Nautex.ai API."""
    
    def __init__(self, api_client: NautexAPIClient, config: NautexConfig):
        """Initialize the API service.
        
        Args:
            api_client: The low-level HTTP client
            config: Application configuration containing API settings
        """
        self.api_client = api_client
        self.config = config
        
        # API configuration
        self.api_base_url = "https://api.nautex.ai"  # Could be configurable in the future
        self.api_version_path = "/d/v1/"
        
        logger.debug(f"NautexAPIService initialized with base URL: {self.api_base_url}")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests.
        
        Returns:
            Dictionary containing Authorization header
        """
        return {
            "Authorization": f"Bearer {self.config.api_token.get_secret_value()}"
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
        base_with_version = urljoin(self.api_base_url, self.api_version_path)
        full_url = urljoin(base_with_version, endpoint_path)
        
        logger.debug(f"Constructed API URL: {full_url}")
        return full_url
    
    # API endpoint implementations
    
    async def verify_token_and_get_account_info(self, token: Optional[str] = None) -> AccountInfo:
        """Verify API token and retrieve account information.
        
        Args:
            token: API token to verify (uses config token if not provided)
            
        Returns:
            Account information
            
        Raises:
            NautexAPIError: If token is invalid or API call fails
        """
        # Use provided token or fall back to config token
        auth_token = token if token else self.config.api_token.get_secret_value()
        
        headers = {"Authorization": f"Bearer {auth_token}"}
        url = self._get_full_api_url("account")
        
        try:
            response_data = await self.api_client.get(url, headers)
            logger.debug("Successfully retrieved account information")
            
            # Parse response into AccountInfo model
            return AccountInfo.model_validate(response_data)
            
        except NautexAPIError as e:
            logger.error(f"Failed to verify token and get account info: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in verify_token_and_get_account_info: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")
    
    async def list_projects(self) -> List[Project]:
        """List all projects available to the user.
        
        Returns:
            List of projects
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url("projects")
        
        try:
            response_data = await self.api_client.get(url, headers)
            logger.debug(f"Successfully retrieved {len(response_data.get('projects', []))} projects")
            
            # Parse response into list of Project models
            projects_data = response_data.get('projects', [])
            return [Project.model_validate(project) for project in projects_data]
            
        except NautexAPIError as e:
            logger.error(f"Failed to list projects: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in list_projects: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")
    
    async def list_implementation_plans(self, project_id: str) -> List[ImplementationPlan]:
        """List implementation plans for a specific project.
        
        Args:
            project_id: ID of the project
            
        Returns:
            List of implementation plans
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/plans")
        
        try:
            response_data = await self.api_client.get(url, headers)
            logger.debug(f"Successfully retrieved {len(response_data.get('plans', []))} implementation plans for project {project_id}")
            
            # Parse response into list of ImplementationPlan models
            plans_data = response_data.get('plans', [])
            return [ImplementationPlan.model_validate(plan) for plan in plans_data]
            
        except NautexAPIError as e:
            logger.error(f"Failed to list implementation plans for project {project_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in list_implementation_plans: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")
    
    async def get_next_task(self, project_id: str, plan_id: str) -> Optional[Task]:
        """Get the next available task for a project/plan.
        
        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            
        Returns:
            Next task or None if no tasks available
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/plans/{plan_id}/tasks/next")
        
        try:
            response_data = await self.api_client.get(url, headers)
            
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
        task_designators: List[str]
    ) -> List[Task]:
        """Get information for specific tasks.
        
        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designators: List of task identifiers
            
        Returns:
            List of tasks
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/plans/{plan_id}/tasks")
        
        # Create request payload
        request_data = {
            "task_designators": task_designators
        }
        
        try:
            response_data = await self.api_client.post(url, headers, request_data)
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
        status: str
    ) -> Task:
        """Update the status of a task.
        
        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designator: Task identifier
            status: New status for the task
            
        Returns:
            Updated task
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/plans/{plan_id}/tasks/{task_designator}/status")
        
        # Create request payload
        request_data = {
            "status": status
        }
        
        try:
            response_data = await self.api_client.post(url, headers, request_data)
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
        content: str
    ) -> Dict[str, Any]:
        """Add a note to a task.
        
        Args:
            project_id: ID of the project
            plan_id: ID of the implementation plan
            task_designator: Task identifier
            content: Note content
            
        Returns:
            Confirmation dictionary
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/plans/{plan_id}/tasks/{task_designator}/notes")
        
        # Create request payload
        request_data = {
            "content": content
        }
        
        try:
            response_data = await self.api_client.post(url, headers, request_data)
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
    
    async def get_requirements_info(
        self, 
        project_id: str, 
        requirement_designators: List[str]
    ) -> List[Requirement]:
        """Get information for specific requirements.
        
        Args:
            project_id: ID of the project
            requirement_designators: List of requirement identifiers
            
        Returns:
            List of requirements
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/requirements")
        
        # Create request payload
        request_data = {
            "requirement_designators": requirement_designators
        }
        
        try:
            response_data = await self.api_client.post(url, headers, request_data)
            logger.debug(f"Successfully retrieved {len(response_data.get('requirements', []))} requirements for project {project_id}")
            
            # Parse response into list of Requirement models
            requirements_data = response_data.get('requirements', [])
            return [Requirement.model_validate(req) for req in requirements_data]
            
        except NautexAPIError as e:
            logger.error(f"Failed to get requirements info for project {project_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_requirements_info: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}")
    
    async def add_requirement_note(
        self, 
        project_id: str, 
        requirement_designator: str, 
        content: str
    ) -> Dict[str, Any]:
        """Add a note to a requirement.
        
        Args:
            project_id: ID of the project
            requirement_designator: Requirement identifier
            content: Note content
            
        Returns:
            Confirmation dictionary
            
        Raises:
            NautexAPIError: If API call fails
        """
        headers = self._get_auth_headers()
        url = self._get_full_api_url(f"projects/{project_id}/requirements/{requirement_designator}/notes")
        
        # Create request payload
        request_data = {
            "content": content
        }
        
        try:
            response_data = await self.api_client.post(url, headers, request_data)
            logger.debug(f"Successfully added note to requirement {requirement_designator}")
            
            # Return confirmation
            return {
                "requirement_designator": requirement_designator,
                "status": "note_added",
                "note_id": response_data.get("note_id"),
                "timestamp": response_data.get("timestamp")
            }
            
        except NautexAPIError as e:
            logger.error(f"Failed to add note to requirement {requirement_designator}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in add_requirement_note: {e}")
            raise NautexAPIError(f"Unexpected error: {str(e)}") 