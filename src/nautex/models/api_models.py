"""Pydantic models for Nautex.ai API request/response structures."""

from typing import List, Optional, Any, Union
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field, validator


class AccountInfo(BaseModel):
    """Account information from Nautex.ai API.

    This model represents the account details returned from the 
    Nautex.ai /d/v1/info/account endpoint after successful token validation.
    """
    profile_email: str = Field(..., description="User's profile email address")
    api_version: str = Field(..., description="API version from the response")

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "profile_email": "user@example.com",
                "api_version": "1.0.0"
            }
        }


class MCPConfigStatus(str, Enum):
    """Status of MCP configuration integration.

    Used by MCPConfigService to indicate the current state
    of the IDE's mcp.json configuration file.
    """
    OK = "OK"
    MISCONFIGURED = "MISCONFIGURED"
    NOT_FOUND = "NOT_FOUND"


class TaskStatus(str, Enum):
    """Valid task status values."""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class RequirementStatus(str, Enum):
    """Valid requirement status values."""
    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    DRAFT = "draft"
    REJECTED = "rejected"


# Core API Models
class Project(BaseModel):
    """Project model from Nautex.ai API.

    Represents a project entity returned from the /d/v1/projects endpoint.
    """
    project_id: str = Field(..., description="Unique project identifier")
    name: str = Field(..., description="Human-readable project name")
    description: Optional[str] = Field(None, description="Project description")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "PROJ-123",
                "name": "E-commerce Platform",
                "description": "Full-stack e-commerce web application"
            }
        }


class ImplementationPlan(BaseModel):
    """Implementation plan model from Nautex.ai API.

    Represents a plan entity returned from the /d/v1/plans/get endpoint.
    """
    plan_id: str = Field(..., description="Unique plan identifier")
    project_id: str = Field(..., description="Parent project identifier")
    name: str = Field(..., description="Human-readable plan name")
    description: Optional[str] = Field(None, description="Plan description")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_id": "PLAN-456",
                "project_id": "PROJ-123",
                "name": "Frontend Implementation",
                "description": "React-based frontend development plan"
            }
        }


class Task(BaseModel):
    """Task model from Nautex.ai API.

    Represents a task entity returned from various /d/v1/tasks endpoints.
    """
    project_id: str = Field(..., description="Parent project identifier")
    plan_id: str = Field(..., description="Parent plan identifier")
    task_designator: str = Field(..., description="Unique task identifier like TASK-123")
    name: str = Field(..., description="Human-readable task name")
    description: str = Field(..., description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    requirements: List[str] = Field(default_factory=list, description="List of requirement designators")
    notes: List[str] = Field(default_factory=list, description="List of task notes")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "PROJ-123",
                "plan_id": "PLAN-456",
                "task_designator": "TASK-789",
                "name": "Implement user authentication",
                "description": "Create login and registration endpoints",
                "status": "todo",
                "requirements": ["REQ-45", "REQ-46"],
                "notes": ["Password hashing requirements clarified"]
            }
        }


class Requirement(BaseModel):
    """Requirement model from Nautex.ai API.

    Represents a requirement entity returned from /d/v1/requirements endpoints.
    """
    project_id: str = Field(..., description="Parent project identifier")
    requirement_designator: str = Field(..., description="Unique requirement identifier like REQ-45")
    name: str = Field(..., description="Human-readable requirement name")
    description: str = Field(..., description="Detailed requirement description")
    status: RequirementStatus = Field(..., description="Current requirement status")
    notes: List[str] = Field(default_factory=list, description="List of requirement notes")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "PROJ-123",
                "requirement_designator": "REQ-45",
                "name": "User Password Security",
                "description": "Passwords must be hashed using Argon2",
                "status": "approved",
                "notes": ["Library recommendation: argon2-cffi"]
            }
        }


class PlanContext(BaseModel):
    """Aggregated context for current plan status.

    This model is used by PlanContextService to provide a comprehensive
    view of the current CLI state, including configuration, API connectivity,
    and next available task.
    """
    config_loaded: bool = Field(..., description="Whether configuration was successfully loaded")
    config_path: Optional[Path] = Field(None, description="Path to the configuration file")
    mcp_status: MCPConfigStatus = Field(..., description="MCP integration status")
    mcp_config_path: Optional[Path] = Field(None, description="Path to the MCP configuration file")
    api_connected: bool = Field(..., description="Whether API connectivity test passed")
    api_response_time: Optional[float] = Field(None, description="API response time in seconds")
    next_task: Optional[Task] = Field(None, description="Next available task from the plan")
    advised_action: str = Field(..., description="Recommended next action for the agent")
    timestamp: str = Field(..., description="Timestamp when the context was created")

    # Using Any for config to avoid circular import with NautexConfig
    config_summary: Optional[Any] = Field(None, description="Summary of current configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "config_loaded": True,
                "config_path": "/path/to/.nautex/config.json",
                "mcp_status": "OK",
                "mcp_config_path": "/path/to/.cursor/mcp.json",
                "api_connected": True,
                "api_response_time": 0.234,
                "next_task": {
                    "task_designator": "TASK-123",
                    "name": "Implement user auth",
                    "status": "todo"
                },
                "advised_action": "Start working on task TASK-123",
                "timestamp": "2024-01-15 14:30:45"
            }
        }


# API Request Models
class ProjectListRequest(BaseModel):
    """Request model for listing projects via /d/v1/projects."""
    project_ids: Optional[List[str]] = Field(None, description="Specific project IDs to retrieve")

    class Config:
        json_schema_extra = {
            "example": {
                "project_ids": ["PROJ-123", "PROJ-456"]
            }
        }


class PlanGetRequest(BaseModel):
    """Request model for getting plans via /d/v1/plans/get."""
    project_id: str = Field(..., description="Project ID to get plans for")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "PROJ-123"
            }
        }


class TaskActionRequest(BaseModel):
    """Base request model for task actions via /d/v1/tasks."""
    action: str = Field(..., description="Action to perform: get_next, get, add_note")
    project_id: str = Field(..., description="Project identifier")
    plan_id: str = Field(..., description="Plan identifier")
    task_designator: Optional[str] = Field(None, description="Specific task designator for single-task actions")
    task_designators: Optional[List[str]] = Field(None, description="Multiple task designators for batch actions")
    content: Optional[str] = Field(None, description="Note content for add_note action")

    @validator('task_designators')
    def validate_task_designators_not_empty(cls, v):
        """Ensure task_designators list is not empty when provided."""
        if v is not None and len(v) == 0:
            raise ValueError('task_designators cannot be an empty list')
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "action": "get_next",
                    "project_id": "PROJ-123",
                    "plan_id": "PLAN-456"
                },
                {
                    "action": "get",
                    "project_id": "PROJ-123",
                    "plan_id": "PLAN-456",
                    "task_designators": ["TASK-789", "TASK-790"]
                },
                {
                    "action": "add_note",
                    "project_id": "PROJ-123",
                    "plan_id": "PLAN-456",
                    "task_designator": "TASK-789",
                    "content": "Implementation notes here"
                }
            ]
        }


class RequirementActionRequest(BaseModel):
    """Base request model for requirement actions via /d/v1/requirements."""
    action: str = Field(..., description="Action to perform: get, update, add_note")
    project_id: str = Field(..., description="Project identifier")
    requirement_designator: Optional[str] = Field(None, description="Single requirement designator")
    requirement_designators: Optional[List[str]] = Field(None, description="Multiple requirement designators")
    content: Optional[str] = Field(None, description="Note content for add_note action")
    description: Optional[str] = Field(None, description="Updated description for update action")
    status: Optional[RequirementStatus] = Field(None, description="Updated status for update action")

    @validator('requirement_designators')
    def validate_requirement_designators_not_empty(cls, v):
        """Ensure requirement_designators list is not empty when provided."""
        if v is not None and len(v) == 0:
            raise ValueError('requirement_designators cannot be an empty list')
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "action": "get",
                    "project_id": "PROJ-123",
                    "requirement_designators": ["REQ-45", "REQ-46"]
                },
                {
                    "action": "add_note",
                    "project_id": "PROJ-123",
                    "requirement_designator": "REQ-45",
                    "content": "Clarification needed on implementation"
                },
                {
                    "action": "update",
                    "project_id": "PROJ-123",
                    "requirement_designator": "REQ-45",
                    "description": "Updated requirement description",
                    "status": "pending_review"
                }
            ]
        }


# API Response Models
class APIResponse(BaseModel):
    """Standardized API response wrapper.

    All Nautex.ai API endpoints return responses in this format.
    """
    status: str = Field(..., description="Response status: success or error")
    data: Optional[Any] = Field(None, description="Response data payload")
    message: Optional[str] = Field(None, description="Human-readable message")
    details: Optional[Any] = Field(None, description="Additional error details")

    @validator('status')
    def validate_status(cls, v):
        """Ensure status is either 'success' or 'error'."""
        if v not in ['success', 'error']:
            raise ValueError('status must be either "success" or "error"')
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "status": "success",
                    "data": {"key": "value"},
                    "message": "Operation completed successfully"
                },
                {
                    "status": "error",
                    "message": "Authentication failed",
                    "details": {"code": 401, "reason": "Invalid token"}
                }
            ]
        } 
