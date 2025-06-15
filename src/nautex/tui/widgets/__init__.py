"""Reusable TUI widgets for the Nautex CLI."""

from .dialogs import ConfirmationDialog
from .inputs import CompactInput, ApiTokenInput, TitledInput
from .layouts import StepByStepLayout, CompactHorizontalLayout
from .lists import TitledOptionList
from .status import StatusDisplay, SetupStatusPanel, AccountStatusPanel
from .views import ConfigurationSummaryView
from .integration import IntegrationStatusWidget, get_shared_integration_status_widget
from .plan_context import PlanContextWidget

__all__ = [
    "ConfirmationDialog",
    "CompactInput",
    "ApiTokenInput",
    "TitledInput",
    "StepByStepLayout",
    "CompactHorizontalLayout",
    "TitledOptionList",
    "StatusDisplay",
    "SetupStatusPanel",
    "AccountStatusPanel",
    "ConfigurationSummaryView",
    "IntegrationStatusWidget",
    "get_shared_integration_status_widget",
    "PlanContextWidget",
]
