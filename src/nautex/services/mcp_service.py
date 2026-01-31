import logging
from typing import Dict, Any, Optional, List, Union

from fastmcp import FastMCP
from mcp.types import TextContent

from . import ConfigurationService, IntegrationStatusService
from .. import __version__
from ..models.config import NautexConfig
from .nautex_api_protocol import NautexAPIProtocol
from ..api.client import NautexAPIError
from ..models.mcp import (
    convert_scope_context_to_mcp_response,
    MCPTaskOperation,
    MCPTaskUpdateResponse,
    format_response_as_markdown,
    ScopeRenderMode,
)
from ..models.scope_rules import get_effective_render_mode
from ..models.config import MCPOutputFormat

from .document_service import DocumentService
from ..api.api_models import TaskOperation
from ..prompts.consts import CMD_NAUTEX_SETUP
from ..api.scope_context_model import TaskStatus

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


def _normalize_sep_lower(value: str) -> str:
    """Normalize a string by lowercasing and collapsing separators to spaces.

    Treats '_', '-' and any whitespace as equivalent separators and reduces
    multiple separators to a single space.
    """
    # Avoid import of re at module top to keep dependencies light here
    import re
    return re.sub(r"[\s_\-]+", " ", value.strip().lower())


def normalize_task_status(value: Optional[Any]) -> Optional[TaskStatus]:
    """Normalize various status inputs to TaskStatus.

    Accepts common variations like enum names (e.g., 'IN_PROGRESS'), hyphen/underscore
    separated forms (e.g., 'in-progress', 'in_progress'), and case-insensitive values.

    If value cannot be matched, raises a ValueError with a message similar to
    Pydantic's enum validation error, but without external links.
    """
    if value is None:
        return None
    if isinstance(value, TaskStatus):
        return value
    if isinstance(value, str):
        norm = _normalize_sep_lower(value)

        # Build lookup allowing both enum .value and .name
        lookup: Dict[str, TaskStatus] = {}
        for st in TaskStatus:
            lookup[_normalize_sep_lower(st.value)] = st
            lookup[_normalize_sep_lower(st.name)] = st

        matched = lookup.get(norm)
        if matched:
            return matched

    # Prepare error similar to Pydantic's, without the docs link
    allowed_vals = [s.value for s in TaskStatus]
    allowed_msg = ", ".join(f"'{v}'" for v in allowed_vals[:-1])
    if allowed_msg:
        allowed_msg = f"{allowed_msg} or '{allowed_vals[-1]}'"
    else:
        allowed_msg = f"'{allowed_vals[-1]}'"

    input_type = type(value).__name__
    input_repr = repr(value)
    msg = (
        "1 validation error for MCPTaskOperation\n"
        "updated_status\n  "
        f"Input should be {allowed_msg} [type=enum, input_value={input_repr}, input_type={input_type}]"
    )
    raise ValueError(msg)

def sanitize_pydantic_error_message(exc: BaseException) -> str:
    """Strip the help URL line from Pydantic error messages.

    Example line removed:
    "For further information visit https://errors.pydantic.dev/..."
    """
    import re
    msg = str(exc)
    msg = re.sub(r"\n\s*For further information visit https?://errors\.pydantic\.dev[^\n]*", "", msg)
    return msg

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
        nautex_api_service: NautexAPIProtocol,
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

    @property
    def response_format(self) -> MCPOutputFormat:
        """Get MCP response format from config."""
        return self.config.response_format

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
    service = _instance

    try:
        logger.debug("Executing status tool")
        status = await service.integration_status_service.get_integration_status()

        if service.config.project_id and service.config.plan_id:
            try:
                # need this to notify API service that MCP is working
                implementation_plan = await service.nautex_api_service.get_implementation_plan(
                    project_id=service.config.project_id,
                    plan_id=service.config.plan_id,
                    from_mcp=True
                )
            except Exception as e:
                logger.error(f"Error retrieving implementation plan: {e}")
                # Continue even if plan retrieval fails
        
        # Prepare response data
        response_data = {
            "version": __version__,
            "status_message": status.get_status_message(from_mcp=True),
            "cwd": str(service.config_service.cwd)
        }

        return {
            "success": True,
            "data": response_data
        }
    except Exception as e:
        logger.error(f"Error in status tool: {e}")
        return {
            "success": False,
            "error": str(e),
            "cwd": str(service.config_service.cwd)
        }

@mcp.tool
async def status() -> List[TextContent]:
    """Get comprehensive status and context information for Nautex CLI."""
    result = await mcp_handle_status()
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        if result.get("success"):
            text = format_response_as_markdown("Status", result["data"])
        else:
            text = format_response_as_markdown("Status Error", result)
        return [TextContent(type="text", text=text)]

    return result


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

        plans = await mcp_service().nautex_api_service.list_implementation_plans(project_id, from_mcp=True)

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


async def mcp_handle_next_scope(full: bool = True) -> Dict[str, Any]:
    """Implementation of the next scope functionality.

    Args:
        full: If True, return full scope tree. If False, return only focus tasks.

    Returns:
        Dict with success status and scope data
    """
    try:
        logger.debug(f"Executing next scope tool (full={full})")
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
            plan_id=service.config.plan_id,
            from_mcp=True
        )

        if next_scope:
            docs_lut = await service.ensure_dependency_documents_on_disk()
            response_scope = convert_scope_context_to_mcp_response(next_scope, docs_lut)

            return {
                "success": True,
                "data": response_scope.render_response(get_effective_render_mode(response_scope, full)),
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
async def next_scope(full: bool = True) -> Union[List[TextContent], Dict[str, Any]]:
    """Get the next scope for the current project and plan.

    Args:
        full: If True (default), returns full scope tree. If False, returns only
              focus tasks for reduced context.
    """
    result = await mcp_handle_next_scope(full=full)
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        if result.get("success"):
            text = format_response_as_markdown("Next Scope", result["data"])
        else:
            text = format_response_as_markdown("Next Scope Error", result)
        return [TextContent(type="text", text=text)]
    return result


async def mcp_handle_update_tasks(operations: List[Dict[str, Any]]) -> MCPTaskUpdateResponse:
    """Update tasks status

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
            try:
                normalized_status = normalize_task_status(op.get("updated_status"))
                mcp_task_operation = MCPTaskOperation(
                    task_designator=op["task_designator"],
                    updated_status=normalized_status,
                    new_note=op.get("new_note")
                )
            except Exception as e:
                return MCPTaskUpdateResponse(
                    success=False,
                    error=sanitize_pydantic_error_message(e)
                )
            mcp_task_operations.append(mcp_task_operation)

        # Convert MCPTaskOperation objects to TaskOperation objects for the API
        task_operations = []
        for op in mcp_task_operations:
            try:
                task_operation = TaskOperation(
                    task_designator=op.task_designator,
                    updated_status=op.updated_status,
                    new_note=op.new_note
                )
            except Exception as e:
                return MCPTaskUpdateResponse(
                    success=False,
                    error=sanitize_pydantic_error_message(e)
                )
            task_operations.append(task_operation)

        response = await service.nautex_api_service.update_tasks(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            operations=task_operations,
            from_mcp=True
        )

        success = response.status == "success"

        # Fetch compact scope to show what's next after update
        # NOTE: Originally was only for DONE transitions, now returns on any successful update.
        # Consider revisiting if this causes context overhead for agents.
        scope_data = None
        # has_done = any(op.updated_status == TaskStatus.DONE for op in mcp_task_operations)
        # if has_done:
        if success:
            try:
                next_scope = await service.nautex_api_service.next_scope(
                    project_id=service.config.project_id,
                    plan_id=service.config.plan_id,
                    from_mcp=True
                )
                if next_scope:
                    docs_lut = await service.ensure_dependency_documents_on_disk()
                    response_scope = convert_scope_context_to_mcp_response(next_scope, docs_lut)
                    scope_data = response_scope.render_response(get_effective_render_mode(response_scope, full=False))
            except Exception as e:
                logger.warning(f"Failed to fetch scope after update: {e}")

        # Determine success based on API response status

        return MCPTaskUpdateResponse(
            success=success,
            updated=response.data,
            message=response.message,
            errors=response.errors,
            next_scope=scope_data
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
            error=sanitize_pydantic_error_message(e)
        )


@mcp.tool
async def update_tasks(operations: List[Dict[str, Any]]) -> Union[List[TextContent], Dict[str, Any]]:
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
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        return [TextContent(type="text", text=response.render_as_markdown_yaml())]
    return response.model_dump(exclude_none=True)
