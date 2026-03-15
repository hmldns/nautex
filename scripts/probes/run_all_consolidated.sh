#!/bin/bash
# Prepare tmux session with prefilled probe commands for manual start.
# Each window has the command typed in — press Enter to run.
#
# Usage: ./run_all_consolidated.sh [timeout]

set -e

SESSION="acp-consolidate"
TIMEOUT="${1:-90}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$PROJECT_DIR/.venv/bin/python"

# Agent probes in order
AGENTS=(
    "gemini:probe_gemini.py"
    "opencode:probe_opencode.py"
    "cursor:probe_cursor.py"
    "claude:probe_claude.py"
    "droid:probe_droid.py"
    "codex:probe_codex.py"
    "goose:probe_goose.py"
    "kiro:probe_kiro.py"
)

# Kill existing session if present
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create session with first agent
FIRST="${AGENTS[0]}"
FIRST_NAME="${FIRST%%:*}"
FIRST_SCRIPT="${FIRST##*:}"
FIRST_CMD="$VENV $SCRIPT_DIR/$FIRST_SCRIPT --consolidate -t $TIMEOUT"
tmux new-session -d -s "$SESSION" -n "$FIRST_NAME" -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION:$FIRST_NAME" "$FIRST_CMD"

# Create windows for remaining agents — command prefilled, not executed
for entry in "${AGENTS[@]:1}"; do
    NAME="${entry%%:*}"
    SCRIPT="${entry##*:}"
    CMD="$VENV $SCRIPT_DIR/$SCRIPT --consolidate -t $TIMEOUT"
    tmux new-window -t "$SESSION" -n "$NAME" -c "$PROJECT_DIR"
    tmux send-keys -t "$SESSION:$NAME" "$CMD"
done

# Select first window
tmux select-window -t "$SESSION:0"

echo "Tmux session '$SESSION' created with ${#AGENTS[@]} windows."
echo "Commands prefilled — press Enter in each window to run."
echo "Attach with: tmux attach -t $SESSION"

# Attach if interactive
if [ -t 0 ]; then
    tmux attach -t "$SESSION"
fi
