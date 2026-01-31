"""Unit tests for TaskTreeStateService."""

import pytest
from nautex.api.scope_context_model import TaskStatus
from .task_tree_state import TaskTreeStateService


class TestInitialLoad:
    """Core: Initial tree loading from scope data."""

    def test_empty_tree_loads_structure(self):
        """Load full tree structure into empty state."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Child', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        assert len(tree) == 2
        assert tree[0] == ('T-1', 'Root', TaskStatus.IN_PROGRESS, 0)
        assert tree[1] == ('T-2', 'Child', TaskStatus.NOT_STARTED, 1)

    def test_multiple_roots_preserve_insertion_order(self):
        """Multiple root tasks preserve insertion order (not sorted)."""
        service = TaskTreeStateService()

        # Load in specific order
        scope = [
            {'designator': 'T-10', 'name': 'Ten', 'status': 'Not started', 'subtasks': []},
            {'designator': 'T-2', 'name': 'Two', 'status': 'Not started', 'subtasks': []},
            {'designator': 'T-1', 'name': 'One', 'status': 'Not started', 'subtasks': []},
        ]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        # Order is preserved from scope insertion, not sorted
        assert [t[0] for t in tree] == ['T-10', 'T-2', 'T-1']

    def test_deep_nesting(self):
        """Three levels of nesting."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'T-1', 'name': 'L0', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'L1', 'status': 'In progress', 'subtasks': [
                    {'designator': 'T-3', 'name': 'L2', 'status': 'Not started', 'subtasks': []}
                ]}
            ]}
        ]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        assert tree[0][3] == 0  # T-1 depth
        assert tree[1][3] == 1  # T-2 depth
        assert tree[2][3] == 2  # T-3 depth


class TestMergeTaskData:
    """Core: Merging task data without structure changes."""

    def test_status_update_preserves_structure(self):
        """Status update with parent context preserves structure."""
        service = TaskTreeStateService()

        # Initial load
        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'Not started', 'subtasks': [
                {'designator': 'T-2', 'name': 'Child', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(scope)

        # Update status - include parent to preserve structure
        update = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'Not started', 'subtasks': [
                {'designator': 'T-2', 'status': 'Done', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(update)

        tree = service.get_flattened_tree()
        assert tree[1][2] == TaskStatus.DONE
        # Structure preserved
        assert len(tree) == 2
        assert tree[1][3] == 1  # Still depth 1

    def test_flat_update_preserves_tree_structure(self):
        """Short form update (no subtasks) preserves tree structure."""
        service = TaskTreeStateService()

        # Initial load with hierarchy
        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'Not started', 'subtasks': [
                {'designator': 'T-2', 'name': 'Child', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(scope)

        # Flat/short form update - only task data, no structure
        update = [
            {'designator': 'T-2', 'status': 'Done'}  # No subtasks key = short form
        ]
        service.update_from_scope_data(update)

        # T-2 status updated but still a child (depth 1)
        tree = service.get_flattened_tree()
        t2 = next(t for t in tree if t[0] == 'T-2')
        assert t2[2] == TaskStatus.DONE
        assert t2[3] == 1  # Still child level

    def test_name_update(self):
        """Name can be updated."""
        service = TaskTreeStateService()

        scope = [{'designator': 'T-1', 'name': 'Original', 'status': 'Not started', 'subtasks': []}]
        service.update_from_scope_data(scope)

        update = [{'designator': 'T-1', 'name': 'Updated', 'status': 'Not started', 'subtasks': []}]
        service.update_from_scope_data(update)

        tree = service.get_flattened_tree()
        assert tree[0][1] == 'Updated'


class TestPartialScope:
    """Core: Partial scope preserves existing tasks."""

    def test_tasks_not_in_scope_preserved(self):
        """Tasks not in partial scope remain in tree."""
        service = TaskTreeStateService()

        # Full tree
        full = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Done', 'status': 'Done', 'subtasks': []},
                {'designator': 'T-3', 'name': 'Active', 'status': 'In progress', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(full)

        # Partial scope - only T-3
        partial = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'Active', 'status': 'Done', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(partial)

        tree = service.get_flattened_tree()
        designators = [t[0] for t in tree]
        assert 'T-2' in designators  # Preserved!
        assert 'T-3' in designators

    def test_children_order_existing_preserved_new_appended(self):
        """Existing children keep order, new children appended at end."""
        service = TaskTreeStateService()

        # Initial: T-1 has children [T-2, T-3]
        full = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'First', 'status': 'Done', 'subtasks': []},
                {'designator': 'T-3', 'name': 'Second', 'status': 'Not started', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(full)

        # Partial scope: T-1 has children [T-3] (T-2 not in scope)
        partial = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'Second', 'status': 'In progress', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(partial)

        tree = service.get_flattened_tree()
        # Existing order preserved: T-2 still first, T-3 still second
        children = [t[0] for t in tree if t[3] == 1]
        assert children == ['T-2', 'T-3']


class TestNewTasks:
    """Core: New tasks appearing in scope."""

    def test_new_root_task_appended(self):
        """New root task appears after existing roots."""
        service = TaskTreeStateService()

        # Initial
        scope = [{'designator': 'T-1', 'name': 'One', 'status': 'Done', 'subtasks': []}]
        service.update_from_scope_data(scope)

        # New root
        new_scope = [{'designator': 'T-17', 'name': 'Seventeen', 'status': 'Not started', 'subtasks': []}]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        designators = [t[0] for t in tree]
        # T-1 (existing) first, T-17 (new) appended after
        assert designators == ['T-1', 'T-17']

    def test_new_child_task_added(self):
        """New child task added to parent."""
        service = TaskTreeStateService()

        # Initial
        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Existing', 'status': 'Done', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(scope)

        # Add new child T-3
        new_scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'New', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        designators = [t[0] for t in tree]
        assert 'T-2' in designators
        assert 'T-3' in designators

    def test_new_child_appended_after_existing_siblings(self):
        """New child task is appended after existing siblings (non-root parent)."""
        service = TaskTreeStateService()

        # Initial: T-1 (root) has children T-2, T-3
        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'First', 'status': 'Done', 'subtasks': []},
                {'designator': 'T-3', 'name': 'Second', 'status': 'In progress', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(scope)

        # New child T-100 arrives (higher number, but should come after existing)
        new_scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'Second', 'status': 'Done', 'subtasks': []},
                {'designator': 'T-100', 'name': 'New Task', 'status': 'Not started', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        children = [t[0] for t in tree if t[3] == 1]  # Depth 1 = children of T-1
        # Existing order preserved: T-2, T-3, then new T-100 at end
        assert children == ['T-2', 'T-3', 'T-100']

    def test_new_root_appended_after_existing_roots(self):
        """New root task is appended after existing roots."""
        service = TaskTreeStateService()

        # Initial: roots T-1 and T-2
        scope = [
            {'designator': 'T-1', 'name': 'First Root', 'status': 'Done', 'subtasks': [
                {'designator': 'T-17', 'name': 'Child', 'status': 'In progress', 'subtasks': []}
            ]},
            {'designator': 'T-2', 'name': 'Second Root', 'status': 'Done', 'subtasks': []},
        ]
        service.update_from_scope_data(scope)

        # New root T-50 arrives
        new_scope = [
            {'designator': 'T-1', 'name': 'First Root', 'status': 'Done', 'subtasks': []},
            {'designator': 'T-50', 'name': 'New Root', 'status': 'Not started', 'subtasks': []},
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        roots = [t[0] for t in tree if t[3] == 0]  # Depth 0 = roots
        # Existing roots preserved in order, new root at end
        assert roots == ['T-1', 'T-2', 'T-50']

    def test_multiple_new_children_preserve_scope_order(self):
        """Multiple new children come in scope order after existing."""
        service = TaskTreeStateService()

        # Initial: T-1 has one child T-2
        scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Existing', 'status': 'Done', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(scope)

        # Two new children T-18 and T-19 arrive
        new_scope = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-18', 'name': 'New First', 'status': 'In progress', 'subtasks': []},
                {'designator': 'T-19', 'name': 'New Second', 'status': 'Not started', 'subtasks': []},
            ]}
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        children = [t[0] for t in tree if t[3] == 1]
        # Existing T-2 first, then new T-18, T-19 in scope order
        assert children == ['T-2', 'T-18', 'T-19']


class TestReparenting:
    """Edge: Task changes parent."""

    def test_task_moves_to_different_parent(self):
        """Task moves from one parent to another."""
        service = TaskTreeStateService()

        # Initial: T-3 under T-1
        scope = [
            {'designator': 'T-1', 'name': 'Parent1', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'Child', 'status': 'Not started', 'subtasks': []}
            ]},
            {'designator': 'T-2', 'name': 'Parent2', 'status': 'Not started', 'subtasks': []}
        ]
        service.update_from_scope_data(scope)

        # Move T-3 to T-2
        new_scope = [
            {'designator': 'T-1', 'name': 'Parent1', 'status': 'In progress', 'subtasks': []},
            {'designator': 'T-2', 'name': 'Parent2', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'Child', 'status': 'In progress', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        # Find T-3's position - should be after T-2 with depth 1
        t3_idx = next(i for i, t in enumerate(tree) if t[0] == 'T-3')
        t2_idx = next(i for i, t in enumerate(tree) if t[0] == 'T-2')

        assert t3_idx > t2_idx  # T-3 comes after T-2
        assert tree[t3_idx][3] == 1  # T-3 has depth 1 (child of T-2)

    def test_task_moves_to_root(self):
        """Task moves from child to root level (requires structured scope)."""
        service = TaskTreeStateService()

        # Initial: T-2 under T-1
        scope = [
            {'designator': 'T-1', 'name': 'Parent', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Child', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(scope)

        # T-2 becomes root - need structured scope (T-1 with no children, T-2 as root)
        new_scope = [
            {'designator': 'T-1', 'name': 'Parent', 'status': 'In progress', 'subtasks': []},
            {'designator': 'T-2', 'name': 'Now Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-3', 'name': 'New child', 'status': 'Not started', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(new_scope)

        tree = service.get_flattened_tree()
        t2 = next(t for t in tree if t[0] == 'T-2')
        assert t2[3] == 0  # Depth 0 = root


class TestFocusTasks:
    """Core: Focus task tracking."""

    def test_focus_task_identified(self):
        """Tasks with in_focus=True are tracked."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'T-1', 'name': 'Not focus', 'status': 'Done', 'subtasks': []},
            {'designator': 'T-2', 'name': 'Focus', 'status': 'In progress',
             'workflow_info': {'in_focus': True}, 'subtasks': []},
        ]
        service.update_from_scope_data(scope)

        assert not service.is_focus_task('T-1')
        assert service.is_focus_task('T-2')

    def test_focus_cleared_on_update(self):
        """Focus is cleared and rebuilt on each update."""
        service = TaskTreeStateService()

        scope1 = [
            {'designator': 'T-1', 'name': 'Focus', 'status': 'In progress',
             'workflow_info': {'in_focus': True}, 'subtasks': []}
        ]
        service.update_from_scope_data(scope1)
        assert service.is_focus_task('T-1')

        scope2 = [
            {'designator': 'T-1', 'name': 'Not focus', 'status': 'Done', 'subtasks': []}
        ]
        service.update_from_scope_data(scope2)
        assert not service.is_focus_task('T-1')


class TestOptimisticUpdates:
    """Core: Optimistic status updates."""

    def test_optimistic_update_applied(self):
        """Optimistic update changes status immediately."""
        service = TaskTreeStateService()

        scope = [{'designator': 'T-1', 'name': 'Task', 'status': 'In progress', 'subtasks': []}]
        service.update_from_scope_data(scope)

        service.apply_status_updates([('T-1', TaskStatus.DONE)])

        tree = service.get_flattened_tree()
        assert tree[0][2] == TaskStatus.DONE
        assert service.is_optimistic('T-1')

    def test_optimistic_cleared_on_scope_update(self):
        """Optimistic flag cleared when scope updates."""
        service = TaskTreeStateService()

        scope = [{'designator': 'T-1', 'name': 'Task', 'status': 'In progress', 'subtasks': []}]
        service.update_from_scope_data(scope)

        service.apply_status_updates([('T-1', TaskStatus.DONE)])
        assert service.is_optimistic('T-1')

        service.update_from_scope_data(scope)
        assert not service.is_optimistic('T-1')

    def test_optimistic_removes_from_focus(self):
        """Marking done removes from focus."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'T-1', 'name': 'Task', 'status': 'In progress',
             'workflow_info': {'in_focus': True}, 'subtasks': []}
        ]
        service.update_from_scope_data(scope)
        assert service.is_focus_task('T-1')

        service.apply_status_updates([('T-1', TaskStatus.DONE)])
        assert not service.is_focus_task('T-1')


class TestShortFormScope:
    """Core: Short form scope (no subtasks) only updates task data."""

    def test_short_form_updates_data_only(self):
        """Short form scope updates status but not structure."""
        service = TaskTreeStateService()

        # Full tree first
        full = [
            {'designator': 'T-1', 'name': 'Root', 'status': 'In progress', 'subtasks': [
                {'designator': 'T-2', 'name': 'Child', 'status': 'In progress', 'subtasks': []}
            ]}
        ]
        service.update_from_scope_data(full)

        # Short form - just task data
        short = [
            {'designator': 'T-2', 'name': 'Child Updated', 'status': 'Done',
             'workflow_info': {'in_focus': False}}
        ]
        service.update_from_scope_data(short)

        tree = service.get_flattened_tree()
        t2 = next(t for t in tree if t[0] == 'T-2')
        assert t2[1] == 'Child Updated'  # Name updated
        assert t2[2] == TaskStatus.DONE   # Status updated
        assert t2[3] == 1                 # Depth preserved (still child)

    def test_new_task_in_short_form_becomes_root(self):
        """New task in short form scope is added as root."""
        service = TaskTreeStateService()

        # Existing tree
        full = [
            {'designator': 'T-1', 'name': 'Existing', 'status': 'Done', 'subtasks': []}
        ]
        service.update_from_scope_data(full)

        # Short form with new task
        short = [
            {'designator': 'T-99', 'name': 'New Task', 'status': 'In progress',
             'workflow_info': {'in_focus': True}}
        ]
        service.update_from_scope_data(short)

        tree = service.get_flattened_tree()
        t99 = next(t for t in tree if t[0] == 'T-99')
        assert t99[3] == 0  # New task added as root
        assert service.is_focus_task('T-99')


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_scope(self):
        """Empty scope doesn't break."""
        service = TaskTreeStateService()

        scope = [{'designator': 'T-1', 'name': 'Task', 'status': 'Done', 'subtasks': []}]
        service.update_from_scope_data(scope)

        service.update_from_scope_data([])

        tree = service.get_flattened_tree()
        assert len(tree) == 1  # Preserved

    def test_task_without_subtasks_key(self):
        """Task without subtasks key handled."""
        service = TaskTreeStateService()

        scope = [{'designator': 'T-1', 'name': 'Task', 'status': 'Done'}]  # No subtasks key
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        assert len(tree) == 1

    def test_reset_clears_all(self):
        """Reset clears all state."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'T-1', 'name': 'Task', 'status': 'In progress',
             'workflow_info': {'in_focus': True}, 'subtasks': []}
        ]
        service.update_from_scope_data(scope)
        service.apply_status_updates([('T-1', TaskStatus.DONE)])

        service.reset()

        assert service.get_flattened_tree() == []
        assert not service.is_focus_task('T-1')
        assert not service.is_optimistic('T-1')

    def test_status_enum_and_string_both_work(self):
        """Status can be string or enum."""
        service = TaskTreeStateService()

        # String status
        scope = [{'designator': 'T-1', 'name': 'Task', 'status': 'Done', 'subtasks': []}]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        assert tree[0][2] == TaskStatus.DONE

    def test_non_numeric_designators_preserve_order(self):
        """Non-numeric designators preserve insertion order."""
        service = TaskTreeStateService()

        scope = [
            {'designator': 'ABC', 'name': 'Alpha', 'status': 'Done', 'subtasks': []},
            {'designator': 'T-1', 'name': 'One', 'status': 'Done', 'subtasks': []},
        ]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        # Order preserved from scope: ABC first, then T-1
        assert tree[0][0] == 'ABC'
        assert tree[1][0] == 'T-1'

    def test_missing_designator_ignored(self):
        """Tasks without designator are skipped."""
        service = TaskTreeStateService()

        scope = [
            {'name': 'No designator', 'status': 'Done', 'subtasks': []},
            {'designator': 'T-1', 'name': 'Has designator', 'status': 'Done', 'subtasks': []},
        ]
        service.update_from_scope_data(scope)

        tree = service.get_flattened_tree()
        assert len(tree) == 1
        assert tree[0][0] == 'T-1'
