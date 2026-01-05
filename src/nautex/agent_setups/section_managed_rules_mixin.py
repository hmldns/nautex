"""Mixin providing DRY validation/ensuring of section-managed rules files.

This mixin encapsulates the shared logic used by agents that:
- store full workflow rules in a file under `.nautex/`
- maintain a root-level file with a managed reference section

Requirements for the consumer class:
- must provide `section_service` (SectionManagedFileService)
- must implement:
    - get_rules_path() -> Path
    - get_root_rules_path() -> Path
    - get_reference_section_content() -> str
    - get_default_rules_template() -> str
- must inherit from AgentSetupBase (for _validate_rules_file, cwd, workflow_rules_content)
"""
from pathlib import Path
from typing import Tuple, Optional

from .base import AgentSetupBase, AgentRulesStatus
from ..prompts.consts import NAUTEX_SECTION_START, NAUTEX_SECTION_END
from ..prompts.common_workflow import get_common_workflow_prompt


class SectionManagedRulesMixin:
    def get_rules_path(self) -> Path:  # pragma: no cover - abstract expectation
        raise NotImplementedError

    def get_root_rules_path(self) -> Path:  # pragma: no cover - abstract expectation
        raise NotImplementedError

    @property
    def workflow_rules_content(self) -> str:  # pragma: no cover - abstract expectation
        raise NotImplementedError

    def get_reference_section_content(self) -> str:  # pragma: no cover - abstract expectation
        raise NotImplementedError

    def get_default_rules_template(self) -> str:  # pragma: no cover - abstract expectation
        raise NotImplementedError

    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        rules_path = self.get_rules_path()

        if not rules_path.exists():
            return AgentRulesStatus.NOT_FOUND, None

        status = self._validate_rules_file(rules_path, self.workflow_rules_content)
        if status != AgentRulesStatus.OK:
            return status, rules_path

        root_path = self.get_root_rules_path()
        if not root_path.exists():
            return AgentRulesStatus.OUTDATED, rules_path

        current_content = root_path.read_text(encoding="utf-8")
        section_bounds = self.section_service.find_section_boundaries(current_content)
        if not section_bounds:
            return AgentRulesStatus.OUTDATED, rules_path

        start, end = section_bounds
        current_section = current_content[start:end]
        expected_section = f"{NAUTEX_SECTION_START}\n\n{self.get_reference_section_content().strip()}\n\n{NAUTEX_SECTION_END}"
        if current_section.strip() != expected_section.strip():
            return AgentRulesStatus.OUTDATED, rules_path

        return AgentRulesStatus.OK, rules_path

    def ensure_rules(self) -> bool:
        try:
            status, _ = self.validate_rules()
            if status == AgentRulesStatus.OK:
                return True

            # Write full rules under .nautex
            rules_path = self.get_rules_path()
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(self.workflow_rules_content, encoding="utf-8")

            # Ensure managed section exists/updated at root file
            root_path = self.get_root_rules_path()
            self.section_service.ensure_file_with_section(
                root_path,
                self.get_reference_section_content(),
                self.get_default_rules_template(),
            )

            final_status, _ = self.validate_rules()
            return final_status == AgentRulesStatus.OK
        except Exception:
            return False


class ConfigAwareSectionManagedRulesMixin(SectionManagedRulesMixin):
    """Mixin that provides workflow_rules_content from config_service.

    Use this instead of SectionManagedRulesMixin when the class has access to
    config_service (from AgentSetupBase inheritance).
    """

    @property
    def workflow_rules_content(self) -> str:
        """Get workflow rules content based on config response format."""
        return get_common_workflow_prompt(self.config_service.config.response_format)
