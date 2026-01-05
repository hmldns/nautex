"""OpenCode agent setup and configuration.

Implements:
- MCP server integration via per-project `opencode.json` (JSON/JSONC compatible write)
- Managed rules: full content under `.nautex/AGENTS.md` and a managed section in root `AGENTS.md`
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple, Optional
import asyncio

from .base import AgentSetupBase
from .section_managed_rules_mixin import ConfigAwareSectionManagedRulesMixin
from ..models.config import AgentType
from ..prompts.consts import (
    NAUTEX_SECTION_START,
    NAUTEX_SECTION_END,
    rules_reference_content_for,
    default_agents_rules_template_for,
    DIR_NAUTEX,
)
from ..services.section_managed_file_service import SectionManagedFileService
from ..utils import path2display
from ..utils.opencode_config_utils import (
    validate_opencode_config_file,
    write_opencode_config,
)
from ..utils.mcp_utils import MCPConfigStatus


class OpenCodeAgentSetup(ConfigAwareSectionManagedRulesMixin, AgentSetupBase):
    """OpenCode agent setup and configuration."""

    def __init__(self, config_service):
        super().__init__(config_service, AgentType.OPENCODE)
        self.section_service = SectionManagedFileService(NAUTEX_SECTION_START, NAUTEX_SECTION_END)

    # ---------- MCP configuration (project opencode.json) ----------
    def get_agent_mcp_config_path(self) -> Path:
        """Prefer per-project config `opencode.json` in project root."""
        return Path("opencode.json")

    def get_global_mcp_config_path(self) -> Path:
        """Global OpenCode config path per docs."""
        return Path.home() / ".config" / "opencode" / "opencode.json"

    async def get_mcp_configuration_info(self) -> str:
        local = self.cwd / self.get_agent_mcp_config_path()
        glob = self.get_global_mcp_config_path()
        return (
            f"OpenCode config (project): {local}\n"
            f"OpenCode config (global):  {glob}\n"
            f"Writes project file; considers global for read-only checks"
        )

    async def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        # Check project config first
        local_path = self.cwd / self.get_agent_mcp_config_path()
        if await asyncio.to_thread(lambda: local_path.exists()):
            status = await asyncio.to_thread(validate_opencode_config_file, local_path)
            return status, local_path

        # Fallback to global for status info
        global_path = self.get_global_mcp_config_path()
        if await asyncio.to_thread(lambda: global_path.exists()):
            status = await asyncio.to_thread(validate_opencode_config_file, global_path)
            return status, global_path

        return MCPConfigStatus.NOT_FOUND, None

    async def write_mcp_configuration(self) -> bool:
        # Always write/update the per-project config file
        target = self.cwd / self.get_agent_mcp_config_path()
        return await asyncio.to_thread(write_opencode_config, target)

    # ---------- Rules management ----------
    def get_rules_path(self) -> Path:
        return self.cwd / DIR_NAUTEX / "AGENTS.md"

    def get_root_rules_path(self) -> Path:
        return self.cwd / "AGENTS.md"

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"

    def get_reference_section_content(self) -> str:
        return rules_reference_content_for("AGENTS.md")

    def get_default_rules_template(self) -> str:
        # Avoid relying on instance type (may be str in some contexts)
        return default_agents_rules_template_for("AGENTS.md", AgentType.OPENCODE.display_name())
