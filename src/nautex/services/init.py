"""Shared MCP service initialization - used by CLI and test harness."""

from typing import Optional
from .config_service import ConfigurationService
from .mcp_service import MCPService, mcp_server_set_service_instance


def init_mcp_services(
    config_service: ConfigurationService,
    integration_status_service: Optional["IntegrationStatusService"] = None,
    nautex_api_service: Optional["NautexAPIService"] = None,
    document_service: Optional["DocumentService"] = None,
) -> MCPService:
    """Initialize MCP service with proper dependencies.

    Used by both the main CLI and test harness. Services can be passed in
    (for reuse) or created fresh.

    Args:
        config_service: Loaded configuration service
        integration_status_service: Optional (main CLI provides, test harness skips)
        nautex_api_service: Optional (reuse existing or create new)
        document_service: Optional (reuse existing or create new)

    Returns:
        Initialized MCPService instance (also set as global)
    """
    from .nautex_api_service import NautexAPIService
    from .document_service import DocumentService
    from ..api import create_api_client

    # Create API service if not provided
    if nautex_api_service is None:
        api_client = create_api_client(base_url=config_service.config.api_host, test_mode=False)
        nautex_api_service = NautexAPIService(api_client, config_service)

    # Create document service if not provided
    if document_service is None:
        document_service = DocumentService(
            nautex_api_service=nautex_api_service,
            config_service=config_service
        )

    # Create MCP service
    mcp_service = MCPService(
        config_service=config_service,
        nautex_api_service=nautex_api_service,
        integration_status_service=integration_status_service,
        document_service=document_service
    )

    # Register global instance
    mcp_server_set_service_instance(mcp_service)

    return mcp_service
