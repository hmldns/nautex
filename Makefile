.PHONY: help install install-dev lint format check test build publish clean run-cli run-setup run-status run-mcp

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
	python3 -m build

publish: clean build
	@echo "Publishing to PyPI..."
	twine upload dist/*

# Run without installation targets
run-cli:
	PYTHONPATH=src python3 -m nautex.cli --help

run-setup:
	PYTHONPATH=src python3 -m nautex.cli setup

run-status:
	PYTHONPATH=src python3 -m nautex.cli status

run-mcp:
	PYTHONPATH=src python3 -m nautex.cli mcp

run-mcp-inspector:
	DANGEROUSLY_OMIT_AUTH=true npx @modelcontextprotocol/inspector

# Cleanup
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	rm -rf venv/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
