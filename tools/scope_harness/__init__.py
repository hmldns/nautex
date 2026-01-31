"""Scope harness - dev tool for testing full/compact scope rendering.

This tool validates the rendering behavior of the next_scope MCP command
by going through the actual MCP layer with a mock API service.

Usage:
    # Run with mock data (TUI):
    make test-scope-interactive

    # Run with mock data (simple test):
    make test-scope

    # Run with real API:
    make test-scope-api-interactive PROJECT_ID=xxx PLAN_ID=yyy
"""

from .mock_api_service import MockNautexAPIService
from .interactive_harness import InteractiveHarness
from .tui import ScopeTestTUI, run_tui

__all__ = [
    "MockNautexAPIService",
    "InteractiveHarness",
    "ScopeTestTUI",
    "run_tui",
]
