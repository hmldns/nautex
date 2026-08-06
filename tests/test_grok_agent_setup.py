"""Tests for Grok Build agent MCP setup and TOML helpers."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Load config_service first to avoid agent_setup <-> services circular import.
from nautex.services.config_service import ConfigurationService  # noqa: F401
from nautex.models.config import AgentType, NautexConfig
from nautex.agent_setups.grok import GrokAgentSetup, GROK_MCP_ENTRY_EXTRAS
from nautex.utils.mcp_toml_utils import (
    validate_mcp_toml_file,
    write_mcp_toml_configuration,
)
from nautex.utils.mcp_utils import MCPConfigStatus
from nautex.setup_noninteractive import AGENT_MAP


def test_agent_type_grok():
    assert AgentType.GROK == "grok"
    assert AgentType.GROK.display_name() == "Grok Build"
    assert AgentType.GROK in AgentType.list()


def test_agent_map_includes_grok():
    assert AGENT_MAP["grok"] is AgentType.GROK


def test_write_and_validate_mcp_toml_basic(tmp_path: Path):
    cfg = tmp_path / ".grok" / "config.toml"
    assert write_mcp_toml_configuration(cfg) is True
    assert validate_mcp_toml_file(cfg) is MCPConfigStatus.OK
    text = cfg.read_text(encoding="utf-8")
    assert "nautex" in text
    assert "uvx" in text


def test_write_mcp_toml_with_extras(tmp_path: Path):
    cfg = tmp_path / ".grok" / "config.toml"
    assert write_mcp_toml_configuration(cfg, entry_extras=GROK_MCP_ENTRY_EXTRAS) is True
    assert validate_mcp_toml_file(cfg) is MCPConfigStatus.OK
    text = cfg.read_text(encoding="utf-8")
    assert "startup_timeout_sec" in text
    assert "20" in text
    assert "enabled" in text


def test_write_preserves_other_servers(tmp_path: Path):
    cfg = tmp_path / ".grok" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '[ui]\nyolo = true\n\n[mcp_servers.other]\ncommand = "echo"\nargs = ["hi"]\n',
        encoding="utf-8",
    )
    assert write_mcp_toml_configuration(cfg, entry_extras=GROK_MCP_ENTRY_EXTRAS) is True
    assert validate_mcp_toml_file(cfg) is MCPConfigStatus.OK
    text = cfg.read_text(encoding="utf-8")
    assert "other" in text
    assert "echo" in text
    assert "nautex" in text


def test_validate_misconfigured(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[mcp_servers.nautex]\ncommand = "python"\nargs = ["-m", "nautex"]\n',
        encoding="utf-8",
    )
    assert validate_mcp_toml_file(cfg) is MCPConfigStatus.MISCONFIGURED


def test_validate_not_found(tmp_path: Path):
    assert validate_mcp_toml_file(tmp_path / "missing.toml") is MCPConfigStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_grok_agent_setup_write_and_check(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config = NautexConfig(agent_type=AgentType.GROK)
    config_service = MagicMock()
    config_service.cwd = tmp_path
    config_service.config = config

    setup = GrokAgentSetup(config_service)

    status, path = await setup.check_mcp_configuration()
    assert status is MCPConfigStatus.NOT_FOUND
    assert path is None

    # Pre-existing config so backup is created
    mcp_path = setup.get_agent_mcp_config_path()
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text("[ui]\ncompact_mode = true\n", encoding="utf-8")

    ok = await setup.write_mcp_configuration()
    assert ok is True

    status, path = await setup.check_mcp_configuration()
    assert status is MCPConfigStatus.OK
    assert path == mcp_path

    assert setup.get_agent_mcp_backup_path().exists()
    text = mcp_path.read_text(encoding="utf-8")
    assert "nautex" in text
    assert "startup_timeout_sec" in text


@pytest.mark.asyncio
async def test_grok_agent_setup_rules(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config = NautexConfig(agent_type=AgentType.GROK)
    config_service = MagicMock()
    config_service.cwd = tmp_path
    config_service.config = config

    setup = GrokAgentSetup(config_service)
    assert setup.ensure_rules() is True
    assert setup.get_rules_path().exists()
    assert setup.get_root_rules_path().exists()
    root = setup.get_root_rules_path().read_text(encoding="utf-8")
    assert "NAUTEX_SECTION_START" in root
