"""Unit tests for dynamic port discovery.

Validates regex parsing of OS port bindings from noisy stdout streams
using mocked process objects.

Reference: MDS-38
"""

import asyncio
import pytest

from nautex.gateway.adapters.port_discovery import (
    discover_dynamic_port,
    PortDiscoveryTimeoutError,
    ProcessStdoutClosedError,
    PORT_REGEX,
)


class FakeStdout:
    """Mock async stdout stream that yields pre-configured lines."""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""  # EOF
        line = self._lines[self._index]
        self._index += 1
        return line


class FakeProcess:
    """Mock asyncio.subprocess.Process with a fake stdout."""

    def __init__(self, stdout_lines: list[bytes]):
        self.stdout = FakeStdout(stdout_lines)
        self.returncode = None


# --- Regex unit tests ---

class TestPortRegex:
    def test_opencode_format(self):
        match = PORT_REGEX.search("Listening on port 12345")
        assert match and int(match.group(1)) == 12345

    def test_droid_format(self):
        match = PORT_REGEX.search("LISTENING ON PORT: 54545")
        assert match and int(match.group(1)) == 54545

    def test_case_insensitive(self):
        match = PORT_REGEX.search("listening ON Port 9999")
        assert match and int(match.group(1)) == 9999

    def test_no_match(self):
        assert PORT_REGEX.search("Starting server...") is None

    def test_noisy_prefix(self):
        match = PORT_REGEX.search("[INFO] 2024-01-01 Listening on port 8080")
        assert match and int(match.group(1)) == 8080


# --- Async discovery tests ---

class TestDiscoverDynamicPort:
    @pytest.mark.asyncio
    async def test_discovers_port_from_clean_output(self):
        proc = FakeProcess([b"Listening on port 54321\n"])
        port = await discover_dynamic_port(proc, timeout=2.0)
        assert port == 54321

    @pytest.mark.asyncio
    async def test_discovers_port_after_noisy_lines(self):
        proc = FakeProcess([
            b"[DEBUG] Initializing agent runtime...\n",
            b"[DEBUG] Loading model weights...\n",
            b"[INFO] Some verbose log output here\n",
            b"Listening on port 8080\n",
        ])
        port = await discover_dynamic_port(proc, timeout=2.0)
        assert port == 8080

    @pytest.mark.asyncio
    async def test_discovers_port_droid_format(self):
        proc = FakeProcess([
            b"Booting droid daemon...\n",
            b"LISTENING ON PORT: 54545\n",
        ])
        port = await discover_dynamic_port(proc, timeout=2.0)
        assert port == 54545

    @pytest.mark.asyncio
    async def test_raises_on_stdout_eof(self):
        proc = FakeProcess([
            b"Some output\n",
            # EOF - no port line
        ])
        with pytest.raises(ProcessStdoutClosedError):
            await discover_dynamic_port(proc, timeout=2.0)

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        class HangingStdout:
            async def readline(self):
                await asyncio.sleep(10)
                return b""

        proc = FakeProcess([])
        proc.stdout = HangingStdout()
        with pytest.raises(PortDiscoveryTimeoutError):
            await discover_dynamic_port(proc, timeout=0.3)

    @pytest.mark.asyncio
    async def test_raises_on_no_stdout(self):
        proc = FakeProcess([])
        proc.stdout = None
        with pytest.raises(ProcessStdoutClosedError):
            await discover_dynamic_port(proc, timeout=1.0)
