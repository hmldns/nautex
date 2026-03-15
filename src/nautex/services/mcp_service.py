"""MCP server layer: FastMCP instance, MCPService class, and thin @mcp.tool wrappers."""

import logging
from typing import Dict, Any, Optional, List, Union

from fastmcp import FastMCP
from mcp.types import TextContent

from . import ConfigurationService, IntegrationStatusService
from ..models.config import NautexConfig, MCPOutputFormat
from .nautex_api_protocol import NautexAPIProtocol
from ..models.mcp import format_response_as_markdown
from .document_service import DocumentService

logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("Nautex AI")

# Global instance variable
_instance: Optional['MCPService'] = None


def mcp_server_set_service_instance(service_instance: 'MCPService') -> None:
    """Set the global MCP service instance."""
    global _instance
    _instance = service_instance
    logger.debug("Global MCP service instance set")


def mcp_server_run() -> None:
    """Run the MCP server in the main thread."""
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
    """Dependency container for MCP tool handlers.

    Holds references to config, API service, document service, and
    integration status service. Handlers in commands.py access this
    via the module-level singleton.
    """

    def __init__(
        self,
        config_service: ConfigurationService,
        nautex_api_service: NautexAPIProtocol,
        integration_status_service: IntegrationStatusService,
        document_service: Optional['DocumentService'] = None,
    ):
        self.config_service = config_service
        self.nautex_api_service = nautex_api_service
        self.document_service = document_service
        self.integration_status_service = integration_status_service
        self._designators_paths: Dict[str, str] = {}
        logger.debug("MCPService initialized with FastMCP server")

    @property
    def config(self) -> NautexConfig:
        return self.config_service.config

    @property
    def response_format(self) -> MCPOutputFormat:
        return self.config.response_format

    async def ensure_dependency_documents(self) -> Dict[str, str]:
        """Fetch dependency documents from backend and write to .nautex/docs/."""
        logger.info("Downloading dependency documents")
        try:
            doc_results = await self.document_service.ensure_plan_dependency_documents(
                project_id=self.config.project_id,
                plan_id=self.config.plan_id,
            )
            successful_loads = sum(
                1 for path in doc_results.values()
                if not path.startswith("Error") and not path.startswith("Document")
            )
            logger.info(f"Downloaded {successful_loads} of {len(doc_results)} dependency documents")
            self._designators_paths = doc_results
        except Exception as e:
            logger.error(f"Error downloading dependency documents: {e}")
            raise
        return self._designators_paths

    @property
    def dependency_documents_paths(self) -> Dict[str, str]:
        """Cached document paths from last download."""
        return self._designators_paths

    def is_configured(self) -> bool:
        return self.config is not None and self.nautex_api_service is not None


# ---------------------------------------------------------------------------
# Thin @mcp.tool wrappers — delegate to handlers in commands.py
# ---------------------------------------------------------------------------

@mcp.tool
async def status() -> Union[List[TextContent], Dict[str, Any]]:
    """Get comprehensive status and context information for Nautex CLI."""
    from ..commands import mcp_handle_status
    response = await mcp_handle_status()
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        text = format_response_as_markdown("Status", response.model_dump(exclude_none=True))
        return [TextContent(type="text", text=text)]
    return response.model_dump(exclude_none=True)


@mcp.tool
async def next_scope(full: bool = False) -> Union[List[TextContent], Dict[str, Any]]:
    """Get the next scope for the current project and plan.

    Args:
        full: If True, force full scope tree. Default is auto mode
              (compact with smart auto-expand).
    """
    from ..commands import mcp_handle_next_scope
    response = await mcp_handle_next_scope(full=full)
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        if response.success and response.data:
            text = format_response_as_markdown("Next Scope", response.data)
        else:
            text = format_response_as_markdown("Next Scope", response.model_dump(exclude_none=True))
        return [TextContent(type="text", text=text)]
    return response.model_dump(exclude_none=True)


@mcp.tool
async def update_tasks(operations: List[Dict[str, Any]]) -> Union[List[TextContent], Dict[str, Any]]:
    """Update multiple tasks in a batch operation.

    Args:
        operations: List of operations, each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status for the task
            - new_note: Optional new note to add to the task
    """
    from ..commands import mcp_handle_update_tasks
    response = await mcp_handle_update_tasks(operations)
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        return [TextContent(type="text", text=response.render_as_markdown_yaml())]
    return response.model_dump(exclude_none=True)


@mcp.tool
async def submit_change_request(
    request_message: str,
    designators: List[str],
    session_id: Optional[str] = None,
    name: Optional[str] = None,
) -> Union[List[TextContent], Dict[str, Any]]:
    """Submit a document change request when you naturally encounter a spec issue during task work.

    Only use when you stumble upon a problem while implementing your tasks — do NOT
    proactively search for spec inconsistencies. Typical situations:
    - A requirement contradicts another requirement or the current codebase
    - Implementation reveals a gap not covered by existing specs
    - A specification is ambiguous and blocks progress
    - The codebase reality has diverged from what the spec describes

    The request creates a review session where the user can approve, reject,
    or discuss the proposed changes.

    Args:
        request_message: Provide full context for the reviewer:
            1) Your task context — what you're working on
            2) The problem — contradiction, gap, or divergence found (reference designators inline)
            3) Impact — how this affects current work
            4) Suggested resolution — what should change in the spec
            Example: "While implementing T-12 (auth service), I found PRD-42 specifies
            API keys but TRD-15 describes OAuth2. These contradict. Suggest updating
            PRD-42 to allow OAuth2."
        designators: Document or item designators that need review
            (e.g., ['PRD', 'TRD-15', 'PRD-42']). Use full document designator
            (e.g., 'PRD') when the change affects the document broadly, or item
            designator (e.g., 'PRD-42') when targeting a specific requirement.
        session_id: Optional existing session ID to continue a prior discussion.
            If omitted, creates a new session.
        name: Optional session title when creating a new session
            (e.g., "Auth flow contradiction between PRD and TRD").
    """
    from ..commands import mcp_handle_submit_change_request
    response = await mcp_handle_submit_change_request(
        request_message, designators, session_id=session_id, name=name,
    )
    if mcp_service().response_format == MCPOutputFormat.MD_YAML:
        text = format_response_as_markdown("Change Request", response.model_dump(exclude_none=True))
        return [TextContent(type="text", text=text)]
    return response.model_dump(exclude_none=True)
