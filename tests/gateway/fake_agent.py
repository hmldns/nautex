"""Fake agent probe script for testing OS subprocess management.

This standalone script simulates a third-party agent binary for integration
testing of process_manager.py and port_discovery.py. It:

- Dumps its environment variables to a JSON file (credential injection verification)
- Emits mock JSON-RPC chunks to stdout (protocol parsing testing)
- Emits the "Listening on port" line for port discovery testing
- Streams massive text to stderr (pipe deadlock stress testing)
- Traps SIGTERM to validate zombie prevention mechanics

Reference: MDS-44
"""

import sys
import time
import os
import json
import signal

# --- Configuration ---
FAKE_PORT = 54321
ENV_DUMP_FILE = "fake_agent_env_dump.json"
STDERR_FLOOD_LINES = 10_000
SIGTERM_TRAPPED = False


def _handle_sigterm(signum, frame):
    """Trap SIGTERM to validate that process_manager escalates to SIGKILL."""
    global SIGTERM_TRAPPED
    SIGTERM_TRAPPED = True
    # Write a marker file so tests can verify SIGTERM was received
    try:
        with open("fake_agent_sigterm_received.marker", "w") as f:
            f.write(f"SIGTERM received at {time.time()}\n")
    except OSError:
        pass
    # Intentionally do NOT exit — forces process_manager to escalate to SIGKILL
    print('{"jsonrpc":"2.0","method":"log","params":{"message":"SIGTERM trapped, not exiting"}}',
          flush=True)


signal.signal(signal.SIGTERM, _handle_sigterm)


if __name__ == "__main__":
    # 1. Dump environment to JSON for credential injection verification
    with open(ENV_DUMP_FILE, "w") as f:
        json.dump(dict(os.environ), f)

    # 2. Emit boot sequence with mock JSON-RPC chunks to stdout
    print('{"jsonrpc":"2.0","method":"log","params":{"message":"Booting fake agent..."}}',
          flush=True)
    time.sleep(0.1)

    # 3. Emit port binding line for port discovery regex testing
    print(f"Listening on port {FAKE_PORT}", flush=True)

    # 4. Flood stderr to stress-test pipe deadlock prevention
    for i in range(STDERR_FLOOD_LINES):
        print(f"[stderr-flood] debug line {i}: " + "x" * 200,
              file=sys.stderr, flush=True)

    # 5. Emit a JSON-RPC notification indicating ready state
    print('{"jsonrpc":"2.0","method":"status","params":{"state":"active"}}',
          flush=True)

    # 6. Run indefinitely until killed
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)
