"""Pydantic models for Nautex.ai API request/response structures."""

from typing import List, Optional, Any, Union
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field, validator
from starlette.responses import JSONResponse


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


class TaskStatus(str, Enum):
    # FIXME duplicated in scope_context_model.py
    NOT_STARTED = "Not started"
    IN_PROGRESS = "In progress"
    DONE = "Done"
    BLOCKED = "Blocked"


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
    description: Optional[str] = Field(..., description="Detailed task description")
    status: TaskStatus = Field(..., description="Current task status")
    requirements: Optional[List[str]] = Field(None, description="List of requirement designators")
    notes: Optional[List[str]] = Field(None, description="List of task notes")

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


class TaskOperation(BaseModel):
    """Model representing a single operation on a task."""
    task_designator: str = Field(..., description="Unique task identifier like TASK-123")
    updated_status: Optional[TaskStatus] = Field(None, description="New status for the task")
    new_note: Optional[str] = Field(None, description="New note content to add to the task")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "task_designator": "TASK-789",
                    "updated_status": "in_progress"
                },
                {
                    "task_designator": "TASK-789",
                    "new_note": "Implementation notes here"
                },
                {
                    "task_designator": "TASK-789",
                    "updated_status": "done",
                    "new_note": "Task completed with additional notes"
                }
            ]
        }


class ErrorMessage(BaseModel):
    # designator: Optional[str] = Field(..., description="")
    message: str = Field(..., description="Error message")


class TaskOperationRequest(BaseModel):
    """Request model for batch task operations."""
    operations: List[TaskOperation] = Field(..., description="List of operations to perform")

    class Config:
        json_schema_extra = {
            "example": {
                "operations": [
                    {
                        "task_designator": "TASK-789",
                        "updated_status": "in_progress"
                    },
                    {
                        "task_designator": "TASK-790",
                        "updated_status": "done"
                    },
                    {
                        "task_designator": "TASK-789",
                        "new_note": "Implementation notes here"
                    },
                    {
                        "task_designator": "TASK-791",
                        "updated_status": "review",
                        "new_note": "Ready for code review"
                    }
                ]
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



# API Response Models
class APIResponse(BaseModel):
    """Standardized API response wrapper.

    All Nautex.ai API endpoints return responses in this format.
    """
    status: str = Field(..., description="Response status: success or error")
    data: Optional[Any] = Field(None, description="Response data payload")
    message: Optional[str] = Field(None, description="Human-readable message")

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


    def to_dict(self):
        rv = self.model_dump(exclude_none=True)
        return rv

    def to_json_response(self) -> JSONResponse:
        return JSONResponse(self.to_dict())
