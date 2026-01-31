"""Codex agent setup and configuration (file-based MCP + AGENT.md)."""
from pathlib import Path
from typing import Tuple, Optional
import subprocess

from .files_based_mcp import FilesBasedMCPAgentSetup
from .section_managed_rules_mixin import ConfigAwareSectionManagedRulesMixin
from .base import AgentRulesStatus
from ..models.config import AgentType
from ..services.section_managed_file_service import SectionManagedFileService
from ..prompts.consts import (
    NAUTEX_SECTION_START,
    NAUTEX_SECTION_END,
    rules_reference_content_for,
    default_agents_rules_template_for,
    DIR_NAUTEX,
)
from ..utils import path2display
from ..utils.mcp_toml_utils import validate_mcp_toml_file, write_mcp_toml_configuration
from ..utils.mcp_utils import MCPConfigStatus
import asyncio


# Default template will be provided via function at call time


class CodexAgentSetup(ConfigAwareSectionManagedRulesMixin, FilesBasedMCPAgentSetup):
    """Codex agent setup and configuration.

    - Uses the project-local TOML MCP config at `.codex/config.toml`.
      Before first write, creates a backup `config.toml.bak` alongside if absent.
    - Manages `.nautex/AGENT.md` with full rules and a root `AGENT.md` including a managed reference section.
    """

    def __init__(self, config_service):
        super().__init__(config_service, AgentType.CODEX)
        self.config_folder = Path(".codex")
        self.rules_filename = Path("AGENTS.md")
        self.section_service = SectionManagedFileService(NAUTEX_SECTION_START, NAUTEX_SECTION_END)

    # ---------- MCP configuration (file-based, mergable) ----------
    def get_agent_mcp_config_path(self) -> Path:
        """Absolute path to the project-local MCP configuration file for Codex agent (TOML)."""
        return self.cwd / ".codex" / "config.toml"

    def get_agent_mcp_backup_path(self) -> Path:
        """Backup path for the Codex MCP configuration file.

        Kept as a separate getter to avoid duplication wherever backup path is needed.
        """
        cfg = self.get_agent_mcp_config_path()
        return cfg.with_suffix(cfg.suffix + ".bak")

    async def get_mcp_configuration_info(self) -> str:
        cfg = self.get_agent_mcp_config_path()
        bak = self.get_agent_mcp_backup_path()
        return (
            f"Codex MCP config (project): {path2display(cfg)}\n"
            f"Backup: creates once as {path2display(bak)} before first write"
        )

    async def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        full_path = self.get_agent_mcp_config_path()
        if await asyncio.to_thread(lambda: full_path.exists()):
            status = await asyncio.to_thread(validate_mcp_toml_file, full_path, self.cwd)
            return status, full_path
        return MCPConfigStatus.NOT_FOUND, None

    async def write_mcp_configuration(self) -> bool:
        full_path = self.get_agent_mcp_config_path()
        # Ensure parent directory exists
        await asyncio.to_thread(lambda: full_path.parent.mkdir(parents=True, exist_ok=True))
        # Create backup once if original exists and backup doesn't
        backup_path = self.get_agent_mcp_backup_path()
        def _maybe_backup():
            if full_path.exists() and not backup_path.exists():
                try:
                    subprocess.run(["cp", str(full_path), str(backup_path)], check=True)
                except Exception:
                    pass
        await asyncio.to_thread(_maybe_backup)
        return await asyncio.to_thread(write_mcp_toml_configuration, full_path, self.cwd)

    # ---------- Rules paths ----------
    def get_rules_path(self) -> Path:
        """Full rules content lives in `.nautex/AGENT.md`."""
        return self.cwd / Path(DIR_NAUTEX) / self.rules_filename

    @property
    def root_agent_path(self) -> Path:
        """Path to the root AGENT.md file (with reference section)."""
        return self.cwd / self.rules_filename

    # ---------- Rules validation / ensure ----------
    def get_root_rules_path(self) -> Path:
        return self.root_agent_path

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"

    def get_reference_section_content(self) -> str:
        return rules_reference_content_for("AGENTS.md")

    def get_default_rules_template(self) -> str:
        # Avoid relying on instance type (may be str in some contexts)
        return default_agents_rules_template_for("AGENTS.md", AgentType.CODEX.display_name())
