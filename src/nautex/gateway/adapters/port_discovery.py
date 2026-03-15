"""Dynamic port discovery for HTTP-bound agent subprocesses.

Parses noisy stdout streams from agent binaries launched with --port 0
to discover the dynamically assigned port via regex matching.

Reference: MDS-31
"""

import re
import asyncio
import logging

logger = logging.getLogger(__name__)

# Case-insensitive regex matches OpenCode ("Listening on port 12345")
# and Droid ("LISTENING ON PORT: 54545")
PORT_REGEX = re.compile(r"(?i)listening on port[:\s]*(\d+)")


class PortDiscoveryTimeoutError(Exception):
    """Raised when agent fails to bind a port within the configured timeout."""
    pass


class ProcessStdoutClosedError(Exception):
    """Raised when agent stdout closes before port discovery completes."""
    pass


async def discover_dynamic_port(
    process: asyncio.subprocess.Process,
    timeout: float = 5.0,
) -> int:
    """Poll agent stdout for a port binding announcement.

    Continuously reads lines from the subprocess stdout and applies
    PORT_REGEX to detect the dynamically assigned port number.

    Args:
        process: The spawned agent subprocess with stdout=PIPE.
        timeout: Maximum seconds to wait for port discovery.

    Returns:
        The discovered port number as an integer.

    Raises:
        PortDiscoveryTimeoutError: If no port is found within timeout.
        ProcessStdoutClosedError: If stdout closes before port is found.
    """
    if not process.stdout:
        raise ProcessStdoutClosedError("Agent stdout pipe is not available.")

    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise PortDiscoveryTimeoutError(
                f"Agent failed to bind port within {timeout}s."
            )

        remaining = timeout - elapsed
        try:
            line_bytes = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=min(remaining, 1.0),
            )
        except asyncio.TimeoutError:
            continue

        if not line_bytes:
            raise ProcessStdoutClosedError(
                "Agent stdout closed before port discovery."
            )

        line = line_bytes.decode("utf-8").strip()
        logger.debug("port_discovery stdout: %s", line)

        match = PORT_REGEX.search(line)
        if match:
            port = int(match.group(1))
            logger.info("Discovered agent port: %d", port)
            return port
