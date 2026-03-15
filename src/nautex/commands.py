"""Command handlers shared by MCP tools and CLI.

Each mcp_handle_*() function contains the business logic for a command.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from .api.api_models import TaskOperation, SubmitChangeRequestPayload
from .api.client import NautexAPIError
from .api.scope_context_model import TaskStatus
from .models.mcp import (
    MCPChangeRequestResponse,
    MCPListPlansResponse,
    MCPListProjectsResponse,
    MCPNextScopeResponse,
    MCPPlanInfo,
    MCPProjectInfo,
    MCPStatusResponse,
    MCPTaskOperation,
    MCPTaskUpdateResponse,
    convert_scope_context_to_mcp_response,
)
from .models.scope_rules import get_effective_render_mode
from .prompts.consts import CMD_NAUTEX_SETUP
from . import __version__

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service instance (set by services/init.py to break circular imports)
# ---------------------------------------------------------------------------

_service_instance = None


def set_service_instance(instance: Any) -> None:
    global _service_instance
    _service_instance = instance


def _get_service():
    if not _service_instance:
        raise RuntimeError("Service not initialized. Call set_service_instance() first.")
    return _service_instance


def _check_configured():
    svc = _get_service()
    if not svc.is_configured():
        return False, {
            "success": False,
            "error": f"Nautex MCP is not configured. Run '{CMD_NAUTEX_SETUP}' to configure the CLI first.",
            "configured": False,
        }
    return True, None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _normalize_sep_lower(value: str) -> str:
    """Normalize a string by lowercasing and collapsing separators to spaces."""
    return re.sub(r"[\s_\-]+", " ", value.strip().lower())


def normalize_task_status(value: Optional[Any]) -> Optional[TaskStatus]:
    """Normalize various status inputs to TaskStatus.

    Accepts common variations like enum names (e.g., 'IN_PROGRESS'), hyphen/underscore
    separated forms (e.g., 'in-progress', 'in_progress'), and case-insensitive values.
    """
    if value is None:
        return None
    if isinstance(value, TaskStatus):
        return value
    if isinstance(value, str):
        norm = _normalize_sep_lower(value)
        lookup: Dict[str, TaskStatus] = {}
        for st in TaskStatus:
            lookup[_normalize_sep_lower(st.value)] = st
            lookup[_normalize_sep_lower(st.name)] = st
        matched = lookup.get(norm)
        if matched:
            return matched

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
    """Strip the help URL line from Pydantic error messages."""
    msg = str(exc)
    msg = re.sub(r"\n\s*For further information visit https?://errors\.pydantic\.dev[^\n]*", "", msg)
    return msg


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def mcp_handle_status() -> MCPStatusResponse:
    """Get comprehensive status and context information."""
    service = _get_service()
    try:
        logger.debug("Executing status tool")
        status = await service.integration_status_service.get_integration_status()

        if service.config.project_id and service.config.plan_id:
            try:
                await service.nautex_api_service.get_implementation_plan(
                    project_id=service.config.project_id,
                    plan_id=service.config.plan_id,
                    from_mcp=True,
                )
            except Exception as e:
                logger.error(f"Error retrieving implementation plan: {e}")

        return MCPStatusResponse(
            success=True,
            version=__version__,
            status_message=status.get_status_message(from_mcp=True),
            cwd=str(service.config_service.cwd),
        )

    except Exception as e:
        logger.error(f"Error in status tool: {e}")
        return MCPStatusResponse(
            success=False,
            error=str(e),
            cwd=str(service.config_service.cwd),
        )


async def mcp_handle_list_projects() -> MCPListProjectsResponse:
    """List all available projects."""
    try:
        logger.debug("Executing list projects tool")
        service = _get_service()

        if not service.is_configured():
            return MCPListProjectsResponse(
                success=False,
                error=f"Nautex CLI is not configured. Run '{CMD_NAUTEX_SETUP}' to configure the CLI first.",
                configured=False,
            )

        projects = await service.nautex_api_service.list_projects()
        return MCPListProjectsResponse(
            success=True,
            projects=[
                MCPProjectInfo(
                    project_id=project.project_id,
                    name=project.name,
                    description=project.description,
                )
                for project in projects
            ],
        )

    except NautexAPIError as e:
        logger.error(f"API error in list projects tool: {e}")
        return MCPListProjectsResponse(success=False, error=f"API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in list projects tool: {e}")
        return MCPListProjectsResponse(success=False, error=str(e))


async def mcp_handle_list_plans(project_id: str) -> MCPListPlansResponse:
    """List implementation plans for a project."""
    try:
        logger.debug(f"Executing list plans tool for project {project_id}")
        configured, error_response = _check_configured()
        if not configured:
            return MCPListPlansResponse(
                success=False,
                error=error_response.get("error", "Configuration error"),
            )

        plans = await _get_service().nautex_api_service.list_implementation_plans(
            project_id, from_mcp=True
        )
        return MCPListPlansResponse(
            success=True,
            plans=[
                MCPPlanInfo(
                    plan_id=plan.plan_id,
                    project_id=plan.project_id,
                    name=plan.name,
                    description=plan.description,
                )
                for plan in plans
            ],
        )

    except NautexAPIError as e:
        logger.error(f"API error in list plans tool: {e}")
        return MCPListPlansResponse(success=False, error=f"API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in list plans tool: {e}")
        return MCPListPlansResponse(success=False, error=str(e))


async def mcp_handle_next_scope(full: bool = False) -> MCPNextScopeResponse:
    """Get the next scope for the current project and plan.

    Args:
        full: If True, force full scope tree. If False (default), use auto mode
              (compact with smart auto-expand rules).
    """
    try:
        logger.debug(f"Executing next scope tool (full={full})")
        service = _get_service()

        configured, error_response = _check_configured()
        if not configured:
            return MCPNextScopeResponse(
                success=False,
                error=error_response.get("error", "Configuration error"),
            )

        if not service.config.project_id or not service.config.plan_id:
            return MCPNextScopeResponse(
                success=False,
                error="Project ID and implementation plan ID must be configured",
            )

        next_scope = await service.nautex_api_service.next_scope(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            from_mcp=True,
        )

        if next_scope:
            docs_lut = await service.ensure_dependency_documents()
            response_scope = convert_scope_context_to_mcp_response(next_scope, docs_lut)
            return MCPNextScopeResponse(
                success=True,
                data=response_scope.render_response(
                    get_effective_render_mode(response_scope, full)
                ),
            )
        else:
            return MCPNextScopeResponse(success=True, message="No next scope available")

    except NautexAPIError as e:
        logger.error(f"API error in next scope tool: {e}")
        return MCPNextScopeResponse(success=False, error=f"API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in next scope tool: {e}")
        return MCPNextScopeResponse(success=False, error=str(e))


async def mcp_handle_update_tasks(
    operations: List[Dict[str, Any]],
) -> MCPTaskUpdateResponse:
    """Update multiple tasks in a batch operation.

    Args:
        operations: List of dicts each containing:
            - task_designator: The designator of the task to update
            - updated_status: Optional new status
            - new_note: Optional note to add
    """
    try:
        logger.debug(f"Executing update tasks tool with {len(operations)} operations")
        service = _get_service()

        configured, error_response = _check_configured()
        if not configured:
            return MCPTaskUpdateResponse(
                success=False,
                error=error_response.get("error", "Configuration error"),
            )

        if not service.config.project_id or not service.config.plan_id:
            return MCPTaskUpdateResponse(
                success=False,
                error="Project ID and implementation plan ID must be configured",
            )

        mcp_task_operations = []
        for op in operations:
            try:
                normalized_status = normalize_task_status(op.get("updated_status"))
                mcp_task_operation = MCPTaskOperation(
                    task_designator=op["task_designator"],
                    updated_status=normalized_status,
                    new_note=op.get("new_note"),
                )
            except Exception as e:
                return MCPTaskUpdateResponse(
                    success=False, error=sanitize_pydantic_error_message(e)
                )
            mcp_task_operations.append(mcp_task_operation)

        task_operations = []
        for op in mcp_task_operations:
            try:
                task_operation = TaskOperation(
                    task_designator=op.task_designator,
                    updated_status=op.updated_status,
                    new_note=op.new_note,
                )
            except Exception as e:
                return MCPTaskUpdateResponse(
                    success=False, error=sanitize_pydantic_error_message(e)
                )
            task_operations.append(task_operation)

        response = await service.nautex_api_service.update_tasks(
            project_id=service.config.project_id,
            plan_id=service.config.plan_id,
            operations=task_operations,
            from_mcp=True,
        )

        success = response.status == "success"

        scope_data = None
        if success:
            try:
                next_scope = await service.nautex_api_service.next_scope(
                    project_id=service.config.project_id,
                    plan_id=service.config.plan_id,
                    from_mcp=True,
                )
                if next_scope:
                    docs_lut = service.dependency_documents_paths
                    if not docs_lut:
                        docs_lut = await service.ensure_dependency_documents()
                    response_scope = convert_scope_context_to_mcp_response(
                        next_scope, docs_lut
                    )
                    scope_data = response_scope.render_response(
                        get_effective_render_mode(response_scope, full=False)
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch scope after update: {e}")

        return MCPTaskUpdateResponse(
            success=success,
            updated=response.data,
            message=response.message,
            errors=response.errors,
            next_scope=scope_data,
        )

    except NautexAPIError as e:
        logger.error(f"API error in update tasks tool: {e}")
        return MCPTaskUpdateResponse(success=False, error=f"API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in update tasks tool: {e}")
        return MCPTaskUpdateResponse(
            success=False, error=sanitize_pydantic_error_message(e)
        )


async def mcp_handle_submit_change_request(
    request_message: str,
    designators: List[str],
    session_id: Optional[str] = None,
    name: Optional[str] = None,
    project_id: Optional[str] = None,
) -> MCPChangeRequestResponse:
    """Submit a document change request. Creates or reuses a review session."""
    try:
        service = _get_service()

        configured, error_response = _check_configured()
        if not configured:
            return MCPChangeRequestResponse(
                success=False,
                error=error_response.get("error", "Configuration error"),
            )

        effective_project_id = project_id or service.config.project_id
        if not effective_project_id:
            return MCPChangeRequestResponse(
                success=False,
                error="Project ID must be configured",
            )

        payload = SubmitChangeRequestPayload(
            request_message=request_message,
            designators=designators,
            author=service.config.agent_instance_name or "Coding Agent",
            session_id=session_id,
            name=name,
        )

        result = await service.nautex_api_service.submit_change_request(
            project_id=effective_project_id,
            payload=payload,
            from_mcp=True,
        )

        return MCPChangeRequestResponse(
            success=True,
            session_id=result.data.get("session_id"),
            session_url=result.data.get("session_url"),
            message="Change request session created. User can review at the session URL.",
        )

    except NautexAPIError as e:
        logger.error(f"API error in submit_change_request tool: {e}")
        return MCPChangeRequestResponse(success=False, error=f"API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in submit_change_request tool: {e}")
        return MCPChangeRequestResponse(
            success=False, error=sanitize_pydantic_error_message(e)
        )
