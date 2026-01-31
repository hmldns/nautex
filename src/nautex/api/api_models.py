"""Pydantic models for Nautex.ai API request/response structures."""

from typing import List, Optional, Any, Dict
from enum import Enum
from pydantic import BaseModel, Field, validator
from starlette.responses import JSONResponse

from .scope_context_model import TaskStatus, TaskType


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
    dependency_documents: Optional[List[str]] = Field(None, description="List of document designators that this plan depends on")

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



# API Response Models
class Node(BaseModel):
    """Node model for document tree.

    Represents a node in a document tree structure.
    """
    title: str = Field(..., description="Node title")
    content: Optional[str] = Field(None, description="Node content")
    relations: Optional[List[Dict[str, Any]]] = Field(None, description="Node relations")
    properties: Optional[Dict[str, Any]] = Field(None, description="Node properties")
    children: Optional[List['Node']] = Field(None, description="Child nodes")
    designator: Optional[str] = Field(None, description="Node designator")


    class Config:
        json_schema_extra = {
            "example": {
                "title": "Introduction",
                "content": "This is the introduction section.",
                "relations": [{"type": "reference", "target": "section-2"}],
                "children": []
            }
        }


class Document(BaseModel):
    """Document model from Nautex.ai API.

    Represents a document tree structure.
    """
    designator: str = Field(..., description="Document designator")
    title: str = Field(..., description="Document title")

    node: Node = Field(..., description="Root node of the document")

    def render_markdown(self) -> str:
        """
        Render the document tree as markdown.

        The format follows these rules:
        - Chapter nodes: #(depth level) [node designator] title
        - Content nodes: [node designator] content (as paragraph)

        Returns:
            A string containing the markdown representation of the document
        """
        lines = []

        # Recursively render nodes
        self._render_node_markdown(self.node, lines, depth=0)

        return "\n".join(lines)


    def render_tree(self) -> str:
        """Render document tree structure as string with descriptions.

        Returns:
            Rendered tree string
        """
        result = []

        # Start with document title
        result.append(f"Document: {self.title} [{self.designator}]")

        # Recursively render nodes
        if self.node:
            result.extend(self._render_node_tree(self.node, indent="  ", is_last=True))

        return "\n".join(result)

    def _render_node_tree(self, node: Node, indent: str = "", is_last: bool = True) -> List[str]:
        """Recursively render a node and its children as a tree structure.

        Args:
            node: The node to render
            indent: Current indentation string
            is_last: Whether this is the last child in current level

        Returns:
            List of strings representing the rendered tree lines
        """
        result = []

        # Get node markers
        marker = "└── " if is_last else "├── "

        # Build the line with title and designator
        line = indent + marker + node.title
        descr = node.properties.get('Description')
        relations_str = self._render_relations(node)

        if descr:
            # Calculate the appropriate indentation for description
            base_len = len(line)
            indent_pos = max(50, base_len + 5)  # Either 50 chars or line length + 5, whichever is greater
            padding = " " * (indent_pos - base_len)
            line += f"{padding}// {descr}"

        if relations_str:
            line += f" {relations_str}"

        result.append(line)

        # Calculate child indent for next level
        child_indent = indent + ("    " if is_last else "│   ")

        # Process children recursively
        if node.children:
            for i, child in enumerate(node.children):
                is_last_child = i == len(node.children) - 1
                result.extend(self._render_node_tree(child, child_indent, is_last_child))

        return result

    def _render_relations(self, node: Node) -> str:
        """Render relations grouped by type.
        
        Groups relations by type and formats them as:
        Type1: Req1, Req2, Req3 | Type2: Req4, Req5
        
        Args:
            node: The node containing relations to render
            
        Returns:
            Formatted relations string or empty string if no relations
        """
        if not node.relations:
            return ""
        
        # Group relations by type
        relations_by_type = {}
        for relation in node.relations:
            relation_type = relation.get('type', 'unknown')
            target = relation.get('target', '')
            if target:
                if relation_type not in relations_by_type:
                    relations_by_type[relation_type] = []
                relations_by_type[relation_type].append(target)
        
        # Create formatted relations string
        relation_parts = []
        for rel_type, targets in relations_by_type.items():
            if targets:
                targets_str = ", ".join(targets)
                relation_parts.append(f"{rel_type.title()}: {targets_str}")

        rels = ' | '.join(relation_parts) if relation_parts else ""

        return f"`Relations {rels}`" if rels else ""

    def _render_node_markdown(self, node: Node, lines: List[str], depth: int = 1):
        """
        Recursively render a node and its children as markdown.

        Args:
            node: The node to render
            lines: List to append markdown lines to
            depth: Current depth level
        """

        # Check if this is a chapter (has title with non-zero length)
        is_chapter = node.title and len(node.title.strip()) > 0

        def _render_designator(_node: Node) -> str:
            if _node.designator:
                return f"[{_node.designator}]"
            else:
                return ""

        designator = _render_designator(node)

        if is_chapter:
            # Add chapter heading with appropriate depth
            heading_level = "#" * (depth + 1)  # +1 because document title is h1
            lines.append(f"{heading_level} {designator} {node.title}")
            # lines.append("")

        # Add content if present
        if node.content:
            relations_str = self._render_relations(node)
            content_lines = node.content.strip().split('\n')
            is_multiline = len(content_lines) > 1
            
            if is_chapter:
                # For chapters, content goes after the heading
                lines.append(node.content)
                if relations_str:
                    lines.append(f"{relations_str}")
            else:

                if is_multiline:
                    lines.append(f"{designator}")
                    lines.extend(content_lines)
                    if relations_str:
                        lines.append(f"{relations_str}")
                else:
                    lines.append(f"{designator} {node.content} {relations_str}")

            lines.append("")

        # Process children recursively
        if node.children:
            for child in node.children:
                self._render_node_markdown(child, lines, depth + 1)

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Requirements Document",
                "node": {
                    "title": "Requirements",
                    "content": "This document outlines the requirements.",
                    "children": [
                        {
                            "title": "Functional Requirements",
                            "content": "List of functional requirements.",
                            "children": []
                        }
                    ]
                }
            }
        }


class DocumentRequest(BaseModel):
    """Request model for getting a document by designator."""
    project_id: str = Field(..., description="Project ID containing the document")
    doc_designator: str = Field(..., description="Document designator")

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "PROJ-123",
                "doc_designator": "DOC-456"
            }
        }


class APIResponse(BaseModel):
    """Standardized API response wrapper.

    All Nautex.ai API endpoints return responses in this format.
    """
    status: str = Field(..., description="Response status: success, partial, or error")
    data: Optional[Any] = Field(None, description="Response data payload")
    message: Optional[str] = Field(None, description="Human-readable message")
    errors: Optional[List[ErrorMessage]] = Field(None, description="List of errors if any occurred")

    @validator('status')
    def validate_status(cls, v):
        """Ensure status is either 'success', 'partial', or 'error'."""
        if v not in ['success', 'partial', 'error']:
            raise ValueError('status must be "success", "partial", or "error"')
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
