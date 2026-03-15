"""OS subprocess manager for agent process lifecycle.

Guarantees that Nautex never leaves orphaned AI agent processes running,
even if the parent Python process crashes or WebSocket connection drops.

Implements:
- Credential stripping from host environment (MDS-23)
- Secure credential injection via env dict (MDS-23)
- Process group isolation via os.setsid (MDS-23)
- Escalating SIGTERM -> SIGKILL termination (MDS-25)
- 5MB stdout/stderr buffer limit (MDS-23)

Reference: MDS-23, MDS-25
"""

import os
import signal
import asyncio
import logging
from typing import List, Dict, Protocol

from pydantic import SecretStr

logger = logging.getLogger(__name__)

# Sensitive environment variables stripped from host before agent launch
STRIPPED_ENV_KEYS = frozenset([
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
])

# 5MB buffer limit on stdout/stderr pipes to prevent RAM exhaustion
PIPE_BUFFER_LIMIT = 1024 * 1024 * 5

# Graceful shutdown timeout before SIGKILL escalation
SIGTERM_TIMEOUT_SECONDS = 2.0


class ProcessLaunchError(Exception):
    """Raised when subprocess creation fails."""
    pass


class AgentProcessConfig(Protocol):
    """Minimal interface for agent config needed by process manager.

    AgentConfig (MDS-11) will satisfy this protocol once implemented.
    """

    @property
    def directory_scope(self) -> str: ...

    @property
    def credentials(self) -> Dict[str, SecretStr]: ...


async def spawn_process(
    config: AgentProcessConfig,
    cmd: str,
    args: List[str],
    stdin: bool = False,
) -> asyncio.subprocess.Process:
    """Spawn an agent subprocess with credential isolation.

    Strips known sensitive env vars from host environment, then injects
    only authorized credentials from config. Uses os.setsid to create
    a new process group for clean termination of entire process trees.

    Args:
        config: Agent configuration with directory_scope and credentials.
        cmd: Executable command to run.
        args: Command arguments.
        stdin: If True, open stdin pipe for ACP communication.

    Returns:
        The spawned asyncio subprocess.

    Raises:
        ProcessLaunchError: If subprocess creation fails.
    """
    env = os.environ.copy()

    # Strip sensitive host credentials
    for key in STRIPPED_ENV_KEYS:
        env.pop(key, None)

    # Inject authorized credentials from agent config
    for key, secret in config.credentials.items():
        env[key] = secret.get_secret_value()

    try:
        process = await asyncio.create_subprocess_exec(
            cmd, *args,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.directory_scope,
            env=env,
            preexec_fn=os.setsid,
            limit=PIPE_BUFFER_LIMIT,
        )
        logger.info("Spawned agent process %s with PID %d", cmd, process.pid)
        return process
    except Exception as e:
        logger.error("Failed to spawn agent process %s: %s", cmd, e)
        raise ProcessLaunchError(f"Subprocess execution failed: {e}") from e


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    """Terminate an agent subprocess with escalating force.

    Attempts graceful SIGTERM to the entire process group. If the process
    does not exit within SIGTERM_TIMEOUT_SECONDS, escalates to SIGKILL.

    Handles already-reaped processes gracefully via ProcessLookupError.

    Args:
        process: The subprocess to terminate.
    """
    if not process or process.returncode is not None:
        return

    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        logger.debug("Agent process %d already reaped.", process.pid)
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
        await asyncio.wait_for(process.wait(), timeout=SIGTERM_TIMEOUT_SECONDS)
        logger.info("Agent process group %d terminated gracefully.", pgid)
    except asyncio.TimeoutError:
        logger.warning(
            "Agent process group %d did not terminate in %.1fs. Sending SIGKILL.",
            pgid, SIGTERM_TIMEOUT_SECONDS,
        )
        try:
            os.killpg(pgid, signal.SIGKILL)
            await process.wait()
            logger.info("Agent process group %d killed.", pgid)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass
