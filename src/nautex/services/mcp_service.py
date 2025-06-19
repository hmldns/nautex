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

# Set up logging
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("Nautex CLI")

# Global instance variable
_instance = None

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

class MCPService:
    """MCP server service using FastMCP library.

    This service implements a FastMCP server that listens for MCP messages over stdio,
    registers tool calls for Nautex CLI functionality, and delegates their execution
    to appropriate service methods.
    """

    def __init__(
        self,
        config: Optional[NautexConfig],
        nautex_api_service: Optional[NautexAPIService],
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

    def _is_configured(self) -> bool:
        """Check if the service is properly configured.

        Returns:
            True if config and API service are available, False otherwise
        """
        return self.config is not None and self.nautex_api_service is not None

# Tool implementations using decorators

@mcp.tool
async def nautex_status() -> Dict[str, Any]:
    """Get comprehensive status and context information for Nautex CLI."""
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
async def nautex_next_task() -> Dict[str, Any]:
    """Get the next available task to work on."""
    try:
        logger.debug("Executing next task tool")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        if not service.config.project_id or not service.config.plan_id:
            return {
                "success": False,
                "error": "Project ID and implementation plan ID must be configured"
            }

        next_task = await service.nautex_api_service.get_next_task(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id
        )

        if next_task:
            return {
                "success": True,
                "data": {
                    "task_designator": next_task.task_designator,
                    "name": next_task.name,
                    "description": next_task.description,
                    "status": next_task.status,
                    "requirements": next_task.requirements,
                    "notes": next_task.notes
                }
            }
        else:
            return {
                "success": True,
                "data": None,
                "message": "No next task available"
            }

    except NautexAPIError as e:
        logger.error(f"API error in next task tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in next task tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def nautex_list_projects() -> Dict[str, Any]:
    """List all available projects."""
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
async def nautex_list_plans(project_id: str) -> Dict[str, Any]:
    """List implementation plans for a project.

    Args:
        project_id: ID of the project to get plans for
    """
    try:
        logger.debug(f"Executing list plans tool for project {project_id}")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        plans = await service.nautex_api_service.list_implementation_plans(project_id)

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
async def nautex_update_task(
    project_id: str, 
    plan_id: str, 
    task_designator: str,
    action: str,
    status: Optional[str] = None,
    content: Optional[str] = None
) -> Dict[str, Any]:
    """Update task status or add notes to a task.

    Args:
        project_id: ID of the project
        plan_id: ID of the implementation plan
        task_designator: Task designator (e.g., TASK-123)
        action: Action to perform (update_status or add_note)
        status: New status for update_status action
        content: Note content for add_note action
    """
    try:
        logger.debug(f"Executing update task tool: {action} for {task_designator}")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        if action == "update_status":
            if not status:
                return {
                    "success": False,
                    "error": "Status is required for update_status action"
                }

            task = await service.nautex_api_service.update_task_status(
                project_id=project_id,
                plan_id=plan_id,
                task_designator=task_designator,
                status=status
            )

            return {
                "success": True,
                "data": {
                    "task_designator": task.task_designator,
                    "name": task.name,
                    "status": task.status,
                    "message": f"Task status updated to {status}"
                }
            }

        elif action == "add_note":
            if not content:
                return {
                    "success": False,
                    "error": "Content is required for add_note action"
                }

            result = await service.nautex_api_service.add_task_note(
                project_id=project_id,
                plan_id=plan_id,
                task_designator=task_designator,
                content=content
            )

            return {
                "success": True,
                "data": result,
                "message": "Note added to task successfully"
            }
        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}"
            }

    except NautexAPIError as e:
        logger.error(f"API error in update task tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in update task tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def nautex_task_info(task_designators: List[str]) -> Dict[str, Any]:
    """Get detailed information for specific tasks by their designators.

    Args:
        task_designators: List of task designators to get info for (e.g., ['TASK-123', 'TASK-124'])
    """
    try:
        logger.debug(f"Executing task info tool for designators: {task_designators}")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        if not service.config.project_id or not service.config.plan_id:
            return {
                "success": False,
                "error": "Project ID and implementation plan ID must be configured"
            }

        tasks = await service.nautex_api_service.get_tasks_info(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            task_designators=task_designators
        )

        return {
            "success": True,
            "data": [
                {
                    "task_designator": task.task_designator,
                    "name": task.name,
                    "description": task.description,
                    "status": task.status,
                    "requirements": task.requirements,
                    "notes": task.notes
                }
                for task in tasks
            ]
        }

    except NautexAPIError as e:
        logger.error(f"API error in task info tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in task info tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def nautex_requirement_info(requirement_designators: List[str]) -> Dict[str, Any]:
    """Get detailed information for specific requirements by their designators.

    Args:
        requirement_designators: List of requirement designators to get info for (e.g., ['REQ-123', 'REQ-124'])
    """
    try:
        logger.debug(f"Executing requirement info tool for designators: {requirement_designators}")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        if not service.config.project_id:
            return {
                "success": False,
                "error": "Project ID must be configured"
            }

        requirements = await service.nautex_api_service.get_requirements_info(
            project_id=service.config.project_id,
            requirement_designators=requirement_designators
        )

        return {
            "success": True,
            "data": [
                {
                    "requirement_designator": req.requirement_designator,
                    "name": req.name,
                    "description": req.description,
                    "status": req.status,
                    "notes": req.notes
                }
                for req in requirements
            ]
        }

    except NautexAPIError as e:
        logger.error(f"API error in requirement info tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in requirement info tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def nautex_requirement_add_note(
    requirement_designator: str, 
    content: str
) -> Dict[str, Any]:
    """Add a note to a specific requirement.

    Args:
        requirement_designator: Requirement designator (e.g., REQ-123)
        content: Note content to add to the requirement
    """
    try:
        logger.debug(f"Executing requirement add note tool for {requirement_designator}")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        if not service.config.project_id:
            return {
                "success": False,
                "error": "Project ID must be configured"
            }

        result = await service.nautex_api_service.add_requirement_note(
            project_id=service.config.project_id,
            requirement_designator=requirement_designator,
            content=content
        )

        return {
            "success": True,
            "data": {
                "requirement_designator": requirement_designator,
                "status": "note_added",
                "result": result
            },
            "message": "Note added to requirement successfully"
        }

    except NautexAPIError as e:
        logger.error(f"API error in requirement add note tool: {e}")
        return {
            "success": False,
            "error": f"API error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in requirement add note tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def nautex_verify_token(token: Optional[str] = None) -> Dict[str, Any]:
    """Verify API token and get account information.

    Args:
        token: API token to verify (optional, uses config token if not provided)
    """
    try:
        logger.debug("Executing verify token tool")
        service = _instance

        if not service._is_configured():
            return {
                "success": False,
                "error": "Nautex CLI is not configured. Run 'nautex setup' to configure the CLI first.",
                "configured": False
            }

        account_info = await service.nautex_api_service.verify_token_and_get_account_info(token)

        # Get latency information from the API service
        _, max_latency = service.nautex_api_service.api_latency

        return {
            "success": True,
            "data": {
                "profile_email": account_info.profile_email,
                "api_version": account_info.api_version,
                "response_latency": max_latency  # Use max latency from the API service
            },
            "message": "Token verification successful"
        }

    except NautexAPIError as e:
        logger.error(f"API error in verify token tool: {e}")
        return {
            "success": False,
            "error": f"Token verification failed: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in verify token tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }
