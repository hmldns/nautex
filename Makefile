.PHONY: help install install-dev lint format check test build publish clean run-cli run-setup run-status run-mcp test-scope test-scope-interactive test-scope-api test-scope-api-interactive install-acp-adapters session-config-probe session-config-probe-list

# Default target
help:
	@echo "Available targets:"
	@echo "  setup        Run the complete setup (recommended)"
	@echo "  venv         Create a virtual environment" 
	@echo "  install-dev  Install the package in development mode with dev dependencies"
	@echo "  install      Install the package in normal mode"
	@echo "  install-wheel         Install built wheel for testing"
	@echo "  install-wheel-user    Install built wheel for current user"
	@echo "  install-wheel-global  Install built wheel globally (requires sudo)"
	@echo "  uninstall-global      Uninstall package globally"
	@echo "  freeze       Generate requirements.txt from current environment"
	@echo "  reinstall-global      Reinstall package globally"
	@echo "  run-cli      Run CLI without installation (shows help)"
	@echo "  run-setup    Run setup command without installation"
	@echo "  run-status   Run status command without installation"
	@echo "  run-mcp      Run MCP server without installation"
	@echo "  run-mcp-inspector  Run MCP inspector without authentication"
	@echo "  test-scope              Run scope test with mock data (non-interactive)"
	@echo "  test-scope-interactive  Run scope test with mock data (interactive)"
	@echo "  test-scope-api          Run scope test with real API (uses config)"
	@echo "  test-scope-api-interactive  Run scope test with real API interactive (uses config)"
	@echo "  lint         Run linters (flake8, mypy)"
	@echo "  format       Format code with black and isort"
	@echo "  check        Run format check without modifying files"
	@echo "  test         Run tests (manual for MVP)"
	@echo "  build        Build the package for distribution"
	@echo "  publish      Publish to PyPI (requires build first)"
	@echo "  clean        Clean build artifacts and virtual environment"

# Complete setup
setup:
	@echo "Running complete setup..."
	./setup.sh

# Virtual environment setup
venv:
	@echo "Creating virtual environment..."
	@if [ ! -d "venv" ]; then \
		python3 -m venv venv; \
		echo "Virtual environment created. Activate with:"; \
		echo "  source venv/bin/activate"; \
	else \
		echo "Virtual environment already exists."; \
	fi

install-wheel:
	@echo "Installing built wheel for testing..."
	pip install dist/*.whl

install-wheel-user:
	@echo "Installing built wheel for current user..."
	pip install --user dist/*.whl

install-wheel-global:
	@echo "Installing built wheel globally (requires sudo)..."
	sudo pip install dist/*.whl

uninstall-global:
	sudo pip uninstall nautex

freeze:
	pip3 freeze > requirements.txt

reinstall-global: uninstall-global install-wheel-global
	@echo "Reinstalled"

# Installation targets
install-dev:
	@echo "Installing in development mode with dev dependencies..."
	@if [ -n "$$VIRTUAL_ENV" ]; then \
		pip install -e .[dev]; \
	else \
		echo "Warning: Not in a virtual environment. Installing with --user flag..."; \
		pip install --user -e .[dev]; \
	fi

# ---------------------------------------------------------------------------
# Dev-mode flag — `NAUTEX_DEV_MODE=1` exposes dev-only providers
# (mock_testing_agent). Central resolver is
# `nautex.gateway.config.is_dev_mode_active`. Dev-facing targets below
# prefix the var; production entry points do not.
# ---------------------------------------------------------------------------

NAUTEX_DEV_MODE := 1
export NAUTEX_DEV_MODE

install:
	@echo "Installing package..."
	@if [ -n "$$VIRTUAL_ENV" ]; then \
		pip install -e .; \
	else \
		echo "Warning: Not in a virtual environment. Installing with --user flag..."; \
		pip install --user -e .; \
	fi

# Code quality targets
lint:
	@echo "Running flake8..."
	flake8 src/nautex/
	@echo "Running mypy..."
	mypy src/nautex/

format:
	@echo "Running black..."
	black src/nautex/
	@echo "Running isort..."
	isort src/nautex/

check:
	@echo "Checking black formatting..."
	black --check src/nautex/
	@echo "Checking isort formatting..."
	isort --check-only src/nautex/
	@echo "Running flake8..."
	flake8 src/nautex/
	@echo "Running mypy..."
	mypy src/nautex/

# Build and publish targets
build:
	@echo "Building package..."
	.venv/bin/python -m build

publish: clean build
	@echo "Publishing to PyPI..."
	twine upload dist/*

# Run without installation targets
run-cli:
	PYTHONPATH=src .venv/bin/python -m nautex.cli --help

run-setup:
	PYTHONPATH=src .venv/bin/python -m nautex.cli setup

run-status:
	PYTHONPATH=src .venv/bin/python -m nautex.cli status

run-mcp:
	PYTHONPATH=src .venv/bin/python -m nautex.cli mcp

run-gateway:
	PYTHONPATH=src .venv/bin/python -m nautex.cli gateway --headless

# Run gateway for local dev — editable install, uplink from .nautex/config.json
run-gateway-local:
	uv run --with-editable . nautex gateway --headless

# Run gateway from parent directory (project root) using editable install venv
run-gateway-parent:
	cd .. && $(CURDIR)/.venv/bin/nautex gateway --headless

run-mcp-inspector:
	DANGEROUSLY_OMIT_AUTH=true npx @modelcontextprotocol/inspector

# ---------------------------------------------------------------------------
# ACP adapter bridges — npm packages that wrap native agent CLIs as ACP peers
# ---------------------------------------------------------------------------

# ACP bridges for agents that don't speak ACP natively. Re-install to pick up
# upstream bug fixes (e.g. permission option changes). The Claude bridge was
# renamed zed-industries → agentclientprotocol; codex stayed on zed-industries.
ACP_ADAPTER_PACKAGES = \
	@agentclientprotocol/claude-agent-acp@latest \
	@zed-industries/codex-acp@latest

# ---------------------------------------------------------------------------
# Session-config probe — run permission/prompt scenarios against real agent
# adapters (claude_code, opencode, codex by default), driving each with a
# specific `AgentSessionConfig`. Artifacts land under
# ~/.nautex/session_config_probe/<timestamp>/ with a top-level index.json
# for LLM review.
# ---------------------------------------------------------------------------

# Override: `make session-config-probe ARGS="--agent claude_code --scenario deny_write"`
ARGS ?= --all

session-config-probe:
	PYTHONPATH=src .venv/bin/python scripts/session_config_probe.py $(ARGS)

session-config-probe-list:
	PYTHONPATH=src .venv/bin/python scripts/session_config_probe.py --list

install-acp-adapters:
	@echo "Installing/updating ACP adapter bridges..."
	npm install -g $(ACP_ADAPTER_PACKAGES)
	@echo ""
	@echo "Installed ACP adapter versions:"
	@npm list -g --depth=0 2>/dev/null | grep -E "claude-agent-acp|codex-acp" || true
	@echo ""
	@echo "Native agent binaries discovered on PATH:"
	@for bin in gemini opencode cursor-agent droid goose kiro-cli; do \
		path=$$(command -v $$bin 2>/dev/null); \
		if [ -n "$$path" ]; then \
			printf "  ✓ %-14s %s\n" "$$bin" "$$path"; \
		else \
			printf "  ✗ %-14s (not found — install separately)\n" "$$bin"; \
		fi; \
	done

dev-claude-mcp-setup:
	cd src && claude mcp remove nautex
	cd src && claude mcp add nautex -s local -- uv run python -m nautex.cli mcp

dev-nautex-setup:
	uv run python -m nautex.cli setup

# Scope testing harness (mock mode - hardcoded sample plan)
test-scope:
	@echo "Running scope rendering test (non-interactive, mock data)..."
	PYTHONPATH=src .venv/bin/python -m tools.scope_harness.cli --mode mock --no-tui

test-scope-interactive:
	@echo "Running scope rendering test interactive (mock data)..."
	PYTHONPATH=src .venv/bin/python -m tools.scope_harness.cli --mode mock

# Scope testing harness (API mode - real backend, uses config if PROJECT_ID/PLAN_ID not provided)
test-scope-api:
	@echo "Running scope rendering test (non-interactive, real API)..."
	PYTHONPATH=src .venv/bin/python -m tools.scope_harness.cli --mode api --no-tui

test-scope-api-interactive:
	@echo "Running scope rendering test interactive (real API)..."
	PYTHONPATH=src .venv/bin/python -m tools.scope_harness.cli --mode api

# Cleanup
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
