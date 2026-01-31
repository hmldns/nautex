"""Mode-agnostic task tree state management service."""

from typing import Dict, List, Optional, Set, Tuple

from nautex.api.scope_context_model import TaskStatus


class TaskTreeStateService:
    """Mode-agnostic service for managing task tree state.

    Processes scope response data to maintain a navigable task tree.
    Uses explicit parent-child relationships for robust tree management.
    """

    def __init__(self):
        # Task data - always preserved and merged
        self._tasks: Dict[str, dict] = {}  # designator -> {name, status}

        # Tree structure - parent relationships
        self._parent: Dict[str, Optional[str]] = {}  # designator -> parent designator (None = root)
        self._children: Dict[str, List[str]] = {}    # designator -> ordered child designators
        self._root_order: List[str] = []             # Ordered list of root designators

        # Transient state
        self._focus_tasks: Set[str] = set()
        self._optimistic_tasks: Set[str] = set()

    def update_from_scope_data(self, tasks_data: List[dict]) -> None:
        """Update tree from scope response. Merges data, updates structure only if present."""
        self._focus_tasks.clear()
        self._optimistic_tasks.clear()

        # Check if scope has tree structure (any task with non-empty subtasks)
        has_structure = self._has_tree_structure(tasks_data)

        # Collect all tasks from response (including nested)
        scope_tasks = self._flatten_scope(tasks_data)

        # 1. Merge task data (status, name) for all tasks in scope
        for designator, info in scope_tasks.items():
            if designator in self._tasks:
                if info.get("status"):
                    self._tasks[designator]["status"] = info["status"]
                if info.get("name"):
                    self._tasks[designator]["name"] = info["name"]
            else:
                self._tasks[designator] = {
                    "name": info.get("name", ""),
                    "status": info.get("status", "Not started"),
                }

            # Update focus
            if info.get("in_focus"):
                self._focus_tasks.add(designator)

        # 2. Update tree structure ONLY if scope has structure
        if has_structure:
            # Collect roots from scope in order (designator is the key)
            scope_roots = [designator for designator, info in scope_tasks.items()
                          if info.get("parent") is None]

            for designator, info in scope_tasks.items():
                parent = info.get("parent")  # None for roots
                children = info.get("children", [])

                # Update parent relationship
                old_parent = self._parent.get(designator)
                if old_parent is not None and old_parent != parent:
                    # Remove from old parent's children (task moved)
                    if old_parent in self._children:
                        self._children[old_parent] = [
                            c for c in self._children[old_parent] if c != designator
                        ]

                # Track root order changes
                if parent is None:
                    # Task is a root
                    if designator not in self._root_order:
                        # New root - append to end
                        self._root_order.append(designator)
                elif designator in self._root_order:
                    # Task was root but now has parent - remove from root order
                    self._root_order.remove(designator)

                # Always set parent (even if None for roots)
                self._parent[designator] = parent

                # Merge children - preserve existing order, append new at end
                existing = self._children.get(designator, [])
                existing_set = set(existing)
                # New tasks = in scope but not already known
                new_tasks = [c for c in children if c not in existing_set]
                # Keep existing order + append new tasks at end
                self._children[designator] = existing + new_tasks
        else:
            # Short form: only add new tasks to tree if not already present
            for designator in scope_tasks:
                if designator not in self._parent:
                    # New task with no structure info - add as root
                    self._parent[designator] = None
                    if designator not in self._root_order:
                        self._root_order.append(designator)

    def _has_tree_structure(self, tasks_data: List[dict]) -> bool:
        """Check if scope has tree structure (any task with children)."""
        for task in tasks_data:
            subtasks = task.get("subtasks", [])
            if subtasks:
                return True
        return False

    def _flatten_scope(self, tasks: List[dict], parent: Optional[str] = None) -> Dict[str, dict]:
        """Flatten nested structure into {designator: {data, parent, children}}."""
        result = {}
        for task in tasks:
            designator = task.get("designator")
            if not designator:
                continue

            child_designators = []
            subtasks = task.get("subtasks", [])
            for st in subtasks:
                if st.get("designator"):
                    child_designators.append(st["designator"])

            result[designator] = {
                "name": task.get("name"),
                "status": task.get("status"),
                "parent": parent,
                "children": child_designators,
                "in_focus": task.get("workflow_info", {}).get("in_focus", False),
            }

            # Recurse
            if subtasks:
                result.update(self._flatten_scope(subtasks, parent=designator))

        return result

    def get_flattened_tree(self) -> List[Tuple[str, str, TaskStatus, int]]:
        """Build display order from tree structure.

        Returns:
            List of (designator, name, status, depth) tuples
        """
        result = []

        # Use tracked root order (preserved insertion order, new appended at end)
        # Filter to only roots that still exist in tasks
        roots = [d for d in self._root_order if d in self._tasks]

        def walk(designator: str, depth: int):
            task = self._tasks.get(designator)
            if not task:
                return
            result.append((
                designator,
                task["name"],
                self._parse_status(task["status"]),
                depth
            ))

            # Walk children in order
            for child in self._children.get(designator, []):
                walk(child, depth + 1)

        for root in roots:
            walk(root, depth=0)

        return result

    def _parse_status(self, status_str) -> TaskStatus:
        """Parse status string to TaskStatus enum."""
        mapping = {
            "Not started": TaskStatus.NOT_STARTED,
            "In progress": TaskStatus.IN_PROGRESS,
            "Done": TaskStatus.DONE,
            "Blocked": TaskStatus.BLOCKED,
        }
        return mapping.get(status_str, TaskStatus.NOT_STARTED)

    def is_focus_task(self, designator: str) -> bool:
        """Check if a task is in focus."""
        return designator in self._focus_tasks

    def apply_status_updates(self, updates: List[Tuple[str, TaskStatus]]) -> None:
        """Optimistically apply status updates to local state.

        Args:
            updates: List of (designator, new_status) tuples
        """
        for designator, status in updates:
            if designator in self._tasks:
                self._tasks[designator]["status"] = status.value
                self._optimistic_tasks.add(designator)
                # Remove from focus if done
                if status == TaskStatus.DONE:
                    self._focus_tasks.discard(designator)

    def is_optimistic(self, designator: str) -> bool:
        """Check if a task has an optimistic (unconfirmed) update."""
        return designator in self._optimistic_tasks

    def clear_optimistic(self) -> None:
        """Clear all optimistic flags (called when scope confirms state)."""
        self._optimistic_tasks.clear()

    def reset(self) -> None:
        """Clear all state."""
        self._tasks.clear()
        self._parent.clear()
        self._children.clear()
        self._root_order.clear()
        self._focus_tasks.clear()
        self._optimistic_tasks.clear()
