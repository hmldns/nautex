"""Plan Context Service for plan and task context management."""

import logging
from datetime import datetime
from typing import Optional

from ..models.plan_context import PlanContext
from ..api.api_models import Task
from .integration_status_service import IntegrationStatusService
from ..api.client import NautexAPIError

# Set up logging
logger = logging.getLogger(__name__)


class PlanContextService:
    """Service for managing plan and task context.

    This service focuses purely on plan-related context including:
    - Current plan and project information
    - Next available tasks
    - Task-specific recommendations
    - Work flow context

    Integration status is handled by IntegrationStatusService.
    """

    def __init__(
        self,
        integration_status_service: IntegrationStatusService
    ):
        """Initialize the plan context service.

        Args:
            integration_status_service: Service for integration status management
        """
        self.integration_status_service = integration_status_service

    async def get_plan_context(self) -> PlanContext:
        """Get plan context with integration status and task information.

        Uses IntegrationStatusService for integration health and adds
        plan-specific context like next available tasks and work recommendations.

        Returns:
            PlanContext with integration status and plan information
        """
        logger.debug("Gathering plan context...")

        # 1. Get integration status from the dedicated service
        integration_status = await self.integration_status_service.get_integration_status()

        # 2. Get next task if integration is ready
        next_task = None
        if integration_status.integration_ready:
            next_task = await self._get_next_task(integration_status)

        # 3. Determine advised action based on integration status and tasks
        advised_action = self._determine_advised_action(integration_status, next_task)

        # 4. Assemble the plan context
        context = PlanContext(
            config_loaded=integration_status.config_loaded,
            config_path=integration_status.config_path,
            mcp_status=integration_status.mcp_status,
            mcp_config_path=integration_status.mcp_config_path,
            api_connected=integration_status.api_connected,
            api_response_time=integration_status.api_response_time,
            next_task=next_task,
            advised_action=advised_action,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            config_summary=integration_status.config_summary
        )

        logger.info(f"Plan context assembled - Action: {advised_action}")
        return context

    async def _get_next_task(self, integration_status) -> Optional[Task]:
        """Get the next available task for the current plan.

        Args:
            integration_status: Integration status containing config and API service

        Returns:
            Next available task or None if no tasks available
        """
        api_service = self.integration_status_service.get_nautex_api_service()
        if not api_service or not integration_status.config_summary:
            return None

        config_summary = integration_status.config_summary
        if not (config_summary.get('project_id') and config_summary.get('plan_id')):
            return None

        try:
            logger.debug("Fetching next available task...")
            next_task = await api_service.get_next_task(
                project_id=config_summary['project_id'],
                plan_id=config_summary['plan_id']
            )
            if next_task:
                logger.debug(f"Next task available: {next_task.task_designator}")
            else:
                logger.debug("No next task available")
            return next_task

        except NautexAPIError as e:
            logger.warning(f"Failed to fetch next task: {e}")
            return None

    def _determine_advised_action(self, integration_status, next_task: Optional[Task]) -> str:
        """Determine the recommended next action based on integration status and tasks.

        Args:
            integration_status: Current integration status
            next_task: Next available task, if any

        Returns:
            Human-readable advised action string
        """
        # If integration is not ready, use its status message
        if not integration_status.integration_ready:
            return integration_status.status_message

        # Integration is ready - focus on task-specific recommendations
        if next_task:
            return f"Start working on task {next_task.task_designator}: {next_task.name}"
        else:
            return "All tasks are completed! Consider adding new tasks or starting a new plan" 
