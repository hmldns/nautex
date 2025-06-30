"""MCP Service for FastMCP server functionality."""

import asyncio
import logging
from typing import Dict, Any, Optional, List
import json

from fastmcp import FastMCP

from ..models.config_models import NautexConfig
from .nautex_api_service import NautexAPIService
from .integration_status_service import IntegrationStatusService
from .plan_context_service import PlanContextService
from .config_service import ConfigurationService
from .mcp_config_service import MCPConfigService
from ..api.client import NautexAPIError
from ..models.mcp_models import convert_scope_context_to_mcp_response

# Set up logging
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("Nautex AI")

# Global instance variable
_instance: Optional['MCPService'] = None


def mcp_server_set_service_instance(service_instance):
    """Set the global MCP service instance.

    Args:
        service_instance: Instance of MCPService to be used by tools
    """
    global _instance
    _instance = service_instance
    logger.debug("Global MCP service instance set")

def mcp_server_run():
    """Run the MCP server in the main thread.

    This should be called from the main thread without an event loop.
    """
    logger.info("Starting Nautex MCP server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"MCP server error: {e}")
        raise


def mcp_service() -> 'MCPService':
    """Get the global MCP service instance."""
    if not _instance:
        raise RuntimeError("MCP service is not initialized. Call mcp_server_set_service_instance() first.")
    return _instance


class MCPService:
    """MCP server service using FastMCP library.

    This service implements a FastMCP server that listens for MCP messages over stdio,
    registers tool calls for Nautex CLI functionality, and delegates their execution
    to appropriate service methods.
    """

    def __init__(
        self,
        config: NautexConfig,
        nautex_api_service: NautexAPIService,
        plan_context_service: PlanContextService
    ):
        """Initialize the MCP service.

        Args:
            config: Nautex configuration (can be None if not configured)
            nautex_api_service: Service for Nautex API operations (can be None if not configured)
            plan_context_service: Service for plan context management
        """
        self.config = config
        self.nautex_api_service = nautex_api_service
        self.plan_context_service = plan_context_service

        logger.debug("MCPService initialized with FastMCP server")

    def is_configured(self) -> bool:
        """Check if the service is properly configured.

        Returns:
            True if config and API service are available, False otherwise
        """
        return self.config is not None and self.nautex_api_service is not None

# Tool implementations using decorators

async def mcp_handle_status() -> Dict[str, Any]:
    """Implementation of the status functionality."""
    try:
        logger.debug("Executing status tool")
        service = _instance
        context = await service.plan_context_service.get_plan_context()

        return {
            "success": True,
            "data": {
                "config_loaded": context.config_loaded,
                "config_path": str(context.config_path) if context.config_path else None,
                "mcp_status": context.mcp_status,
                "mcp_config_path": str(context.mcp_config_path) if context.mcp_config_path else None,
                "api_connected": context.api_connected,
                "api_response_time": context.api_response_time,
                "next_task": {
                    "task_designator": context.next_task.task_designator,
                    "name": context.next_task.name,
                    "description": context.next_task.description,
                    "status": context.next_task.status
                } if context.next_task else None,
                "advised_action": context.advised_action,
                "config_summary": context.config_summary
            }
        }
    except Exception as e:
        logger.error(f"Error in status tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool
async def nautex_status() -> Dict[str, Any]:
    """Get comprehensive status and context information for Nautex CLI."""
    return await mcp_handle_status()


async def mcp_handle_list_projects() -> Dict[str, Any]:
    """Implementation of the list projects functionality."""
    try:
        logger.debug("Executing list projects tool")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        projects = await service.nautex_api_service.list_projects()

        return {
            "success": True,
            "data": [
                {
                    "project_id": project.project_id,
                    "name": project.name,
                    "description": project.description
                }
                for project in projects
            ]
        }

    except NautexAPIError as e:
        logger.error(f"API error in list projects tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in list projects tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool
async def nautex_list_projects() -> Dict[str, Any]:
    """List all available projects."""
    return await mcp_handle_list_projects()


def _check_configured():
    if not mcp_service().is_configured():
        return False, {
            "success": False,
            "error": "Nautex MCP is not configured. Run 'nautex setup' to configure the CLI first.",
            "configured": False
        }

    return True, None


async def mcp_handle_list_plans(project_id: str) -> Dict[str, Any]:
    """Implementation of the list plans functionality.

    Args:
        project_id: ID of the project to get plans for
    """
    try:
        logger.debug(f"Executing list plans tool for project {project_id}")

        configured, error_response = _check_configured()
        if not configured:
            return error_response

        plans = await mcp_service().nautex_api_service.list_implementation_plans(project_id)

        return {
            "success": True,
            "data": [
                {
                    "plan_id": plan.plan_id,
                    "project_id": plan.project_id,
                    "name": plan.name,
                    "description": plan.description
                }
                for plan in plans
            ]
        }

    except NautexAPIError as e:
        logger.error(f"API error in list plans tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in list plans tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool
async def nautex_list_plans(project_id: str) -> Dict[str, Any]:
    """List implementation plans for a project.

    Args:
        project_id: ID of the project to get plans for
    """
    return await mcp_handle_list_plans(project_id)


async def mcp_handle_next_scope() -> Dict[str, Any]:
    """Implementation of the next scope functionality."""
    try:
        logger.debug("Executing next scope tool")
        service = _instance

        configured, error_response = _check_configured()
        if not configured:
            return error_response

        if not service.config.project_id or not service.config.plan_id:
            return {
                "success": False,
                "error": "Project ID and implementation plan ID must be configured"
            }

        next_scope = await service.nautex_api_service.next_scope(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id
        )

        if next_scope:
            # Convert the scope to a dictionary representation
            response_scope = convert_scope_context_to_mcp_response(next_scope)
            return {
                "success": True,
                "data": response_scope.model_dump(),
            }
        else:
            return {
                "success": True,
                "data": None,
                "message": "No next scope available"
            }

    except NautexAPIError as e:
        logger.error(f"API error in next scope tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in next scope tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool
async def nautex_next_scope() -> Dict[str, Any]:
    """Get the next scope for the current project and plan."""
    return await mcp_handle_next_scope()


async def mcp_handle_update_tasks(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Implementation of the update tasks functionality.

    Args:
        operations: List of operations, each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status for the task
            - new_note: Optional new note to add to the task
    """
    try:
        logger.debug(f"Executing update tasks tool with {len(operations)} operations")
        service = _instance

        configured, error_response = _check_configured()
        if not configured:
            return error_response

        if not service.config.project_id or not service.config.plan_id:
            return {
                "success": False,
                "error": "Project ID and implementation plan ID must be configured"
            }

        from src.nautex.api.api_models import TaskOperation

        # Convert the operations to TaskOperation objects
        task_operations = []
        for op in operations:
            task_operation = TaskOperation(
                task_designator=op["task_designator"],
                updated_status=op.get("updated_status"),
                new_note=op.get("new_note")
            )
            task_operations.append(task_operation)

        response = await service.nautex_api_service.update_tasks(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            operations=task_operations
        )

        return {
            "success": True,
            "data": response.data,
            "message": response.message
        }

    except NautexAPIError as e:
        logger.error(f"API error in update tasks tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in update tasks tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool
async def nautex_update_tasks(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Update multiple tasks in a batch operation.

    Args:
        operations: List of operations, each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status for the task
            - new_note: Optional new note to add to the task
    """
    return await mcp_handle_update_tasks(operations)
