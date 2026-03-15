"""Integration tests for OS subprocess manager lifecycle.

Spawns real fake_agent.py processes to verify:
- SIGTERM trapping and SIGKILL fallback reaps process group (MDS-25)
- Credential stripping prevents host API key leakage (MDS-23)
- Authorized credentials are injected via env dict (MDS-23)

Reference: MDS-38
"""

import os
import json
import asyncio
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

import pytest
from pydantic import SecretStr

from nautex.gateway.adapters.process_manager import (
    spawn_process,
    terminate_process,
    STRIPPED_ENV_KEYS,
)

# Path to the fake_agent.py test harness
FAKE_AGENT_PATH = str(Path(__file__).parent / "fake_agent.py")


@dataclass
class FakeAgentConfig:
    """Minimal config satisfying AgentProcessConfig protocol."""
    directory_scope: str = ""
    credentials: Dict[str, SecretStr] = field(default_factory=dict)


def _is_process_alive(pid: int) -> bool:
    """Check if a process exists via os.kill signal 0."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not owned by us


class TestProcessTermination:
    """Verify SIGTERM -> SIGKILL escalation reaps the process group."""

    @pytest.mark.asyncio
    async def test_sigkill_fallback_reaps_process(self):
        """fake_agent.py traps SIGTERM, so terminate_process must escalate to SIGKILL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeAgentConfig(
                directory_scope=tmpdir,
                credentials={},
            )
            proc = await spawn_process(config, "python", [FAKE_AGENT_PATH])
            pid = proc.pid

            # Wait for the agent to boot and emit port line
            assert proc.stdout is not None
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
            assert b"Booting" in line or b"jsonrpc" in line

            # Agent is alive
            assert _is_process_alive(pid)

            # Terminate — fake_agent traps SIGTERM, so this must escalate to SIGKILL
            await terminate_process(proc)

            # Process must be reaped
            assert not _is_process_alive(pid), (
                f"Process {pid} still alive after terminate_process"
            )

    @pytest.mark.asyncio
    async def test_terminate_already_exited_process(self):
        """terminate_process handles already-exited processes gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeAgentConfig(directory_scope=tmpdir, credentials={})
            proc = await spawn_process(config, "python", ["-c", "pass"])
            await proc.wait()  # let it finish naturally
            # Should not raise
            await terminate_process(proc)

    @pytest.mark.asyncio
    async def test_terminate_none_process(self):
        """terminate_process handles None process gracefully."""
        await terminate_process(None)


class TestCredentialIsolation:
    """Verify credential stripping and injection via env dump."""

    @pytest.mark.asyncio
    async def test_host_keys_stripped_from_subprocess(self):
        """Sensitive host env vars must NOT appear in the subprocess environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set a sensitive key in the current process env
            original_value = os.environ.get("ANTHROPIC_API_KEY")
            os.environ["ANTHROPIC_API_KEY"] = "host-secret-should-not-leak"

            try:
                config = FakeAgentConfig(
                    directory_scope=tmpdir,
                    credentials={},
                )
                proc = await spawn_process(config, "python", [FAKE_AGENT_PATH])

                # Wait for agent to write env dump
                await asyncio.sleep(0.5)
                await terminate_process(proc)

                env_dump_path = Path(tmpdir) / "fake_agent_env_dump.json"
                assert env_dump_path.exists(), "fake_agent did not write env dump"

                with open(env_dump_path) as f:
                    child_env = json.load(f)

                # The stripped key must not be in the child's environment
                assert "ANTHROPIC_API_KEY" not in child_env, (
                    "ANTHROPIC_API_KEY leaked into subprocess environment"
                )
            finally:
                # Restore original env state
                if original_value is not None:
                    os.environ["ANTHROPIC_API_KEY"] = original_value
                else:
                    os.environ.pop("ANTHROPIC_API_KEY", None)

    @pytest.mark.asyncio
    async def test_authorized_credentials_injected(self):
        """Credentials from AgentConfig must appear in the subprocess environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_value = "injected-test-secret-12345"
            config = FakeAgentConfig(
                directory_scope=tmpdir,
                credentials={"MY_AGENT_KEY": SecretStr(secret_value)},
            )
            proc = await spawn_process(config, "python", [FAKE_AGENT_PATH])

            # Wait for agent to write env dump
            await asyncio.sleep(0.5)
            await terminate_process(proc)

            env_dump_path = Path(tmpdir) / "fake_agent_env_dump.json"
            assert env_dump_path.exists()

            with open(env_dump_path) as f:
                child_env = json.load(f)

            assert child_env.get("MY_AGENT_KEY") == secret_value, (
                "Authorized credential was not injected into subprocess env"
            )

    @pytest.mark.asyncio
    async def test_host_env_not_contaminated(self):
        """Injecting credentials into subprocess must not modify host os.environ."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeAgentConfig(
                directory_scope=tmpdir,
                credentials={"INJECTED_SECRET": SecretStr("should-not-leak-to-host")},
            )
            proc = await spawn_process(config, "python", [FAKE_AGENT_PATH])
            await asyncio.sleep(0.3)
            await terminate_process(proc)

            assert "INJECTED_SECRET" not in os.environ, (
                "Credential injection contaminated host os.environ"
            )
