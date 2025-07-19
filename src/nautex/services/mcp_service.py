import logging
from typing import Dict, Any, Optional, List

from fastmcp import FastMCP

from . import ConfigurationService, IntegrationStatusService
from ..models.config import NautexConfig
from .nautex_api_service import NautexAPIService
from ..api.client import NautexAPIError
from ..models.mcp import convert_scope_context_to_mcp_response, MCPTaskOperation, MCPTaskUpdateRequest, MCPTaskUpdateResponse

from .document_service import DocumentService
from ..api.api_models import TaskOperation
from ..prompts.consts import CMD_NAUTEX_SETUP

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
        config_service: ConfigurationService,
        nautex_api_service: NautexAPIService,
        integration_status_service: IntegrationStatusService,
        document_service: Optional['DocumentService'] = None
    ):
        """Initialize the MCP service.

        Args:
            config: Nautex configuration (can be None if not configured)
            nautex_api_service: Service for Nautex API operations (can be None if not configured)
            document_service: Service for document operations (optional)
        """
        self.config_service = config_service
        self.nautex_api_service = nautex_api_service
        self.document_service = document_service
        self.integration_status_service = integration_status_service
        self._documents_loaded_for_session = False
        self._designators_paths: Dict[str, str] = {}

        logger.debug("MCPService initialized with FastMCP server")

    @property
    def config(self) -> NautexConfig:
        return self.config_service.config

    async def ensure_dependency_documents_on_disk(self) -> Dict[str, str]:
        # Ensure dependency documents are loaded once per session

        if not self._documents_loaded_for_session:
            logger.info("Loading dependency documents for the current session")
            try:
                # Ensure all dependency documents are available locally
                doc_results = await self.document_service.ensure_plan_dependency_documents(
                    project_id=self.config.project_id,
                    plan_id=self.config.plan_id
                )

                # Count successful loads (paths that don't contain error messages)
                successful_loads = sum(1 for path in doc_results.values() if not path.startswith("Error") and not path.startswith("Document"))
                logger.info(f"Loaded {successful_loads} of {len(doc_results)} dependency documents")

                # Mark documents as loaded for this session
                self._documents_loaded_for_session = True
                self._designators_paths = doc_results

            except Exception as e:
                logger.error(f"Error loading dependency documents: {e}")
                raise

        return self._designators_paths

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
        status = await service.integration_status_service.get_integration_status()

        return {
            "success": True,
            "data": {
                "status_message": status.status_message
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

        if not service.is_configured():
            return {
                "success": False,
                "error": f"Nautex CLI is not configured. Run '{CMD_NAUTEX_SETUP}' to configure the CLI first.",
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


# @mcp.tool
# async def nautex_list_projects() -> Dict[str, Any]:
#     """List all available projects."""
#     return await mcp_handle_list_projects()


def _check_configured():
    if not mcp_service().is_configured():
        return False, {
            "success": False,
            "error": f"Nautex MCP is not configured. Run '{CMD_NAUTEX_SETUP}' to configure the CLI first.",
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


# @mcp.tool()
# async def nautex_list_plans(project_id: str) -> Dict[str, Any]:
#     """List implementation plans for a project.
#
#     Args:
#         project_id: ID of the project to get plans for
#     """
#     return await mcp_handle_list_plans(project_id)


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

            docs_lut = await service.ensure_dependency_documents_on_disk()

            response_scope = convert_scope_context_to_mcp_response(next_scope, docs_lut)
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


async def mcp_handle_update_tasks(operations: List[Dict[str, Any]]) -> MCPTaskUpdateResponse:
    """Implementation of the update tasks functionality.

    Args:
        operations: List of operations, each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status for the task
            - updated_type: Optional new type for the task
            - new_note: Optional new note to add to the task

    Returns:
        MCPTaskUpdateResponse with the result of the operation
    """
    try:
        logger.debug(f"Executing update tasks tool with {len(operations)} operations")
        service = _instance

        configured, error_response = _check_configured()
        if not configured:
            return MCPTaskUpdateResponse(
                success=False,
                error=error_response.get("error", "Configuration error")
            )

        if not service.config.project_id or not service.config.plan_id:
            return MCPTaskUpdateResponse(
                success=False,
                error="Project ID and implementation plan ID must be configured"
            )


        # Convert the operations to MCPTaskOperation objects
        mcp_task_operations = []
        for op in operations:
            mcp_task_operation = MCPTaskOperation(
                task_designator=op["task_designator"],
                updated_status=op.get("updated_status"),
                updated_type=op.get("updated_type"),
                new_note=op.get("new_note")
            )
            mcp_task_operations.append(mcp_task_operation)

        # Convert MCPTaskOperation objects to TaskOperation objects for the API
        task_operations = []
        for op in mcp_task_operations:
            task_operation = TaskOperation(
                task_designator=op.task_designator,
                updated_status=op.updated_status,
                updated_type=op.updated_type,
                new_note=op.new_note
            )
            task_operations.append(task_operation)

        response = await service.nautex_api_service.update_tasks(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            operations=task_operations
        )

        return MCPTaskUpdateResponse(
            success=True,
            data=response.data,
            message=response.message
        )

    except NautexAPIError as e:
        logger.error(f"API error in update tasks tool: {e}")
        return MCPTaskUpdateResponse(
            success=False,
            error=f"API error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error in update tasks tool: {e}")
        return MCPTaskUpdateResponse(
            success=False,
            error=str(e)
        )


@mcp.tool
async def nautex_update_tasks(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Update multiple tasks in a batch operation.

    Args:
        operations: List of operations, each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status for the task
            - updated_type: Optional new type for the task
            - new_note: Optional new note to add to the task

    Returns:
        Dictionary with the result of the operation:
        - success: Whether the operation was successful
        - data: Response data payload if successful
        - message: Human-readable message if provided
        - error: Error message if not successful
    """
    response = await mcp_handle_update_tasks(operations)
    return response.model_dump(exclude_none=True)
