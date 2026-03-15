# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- NAUTEX_SECTION_START -->

# Nautex MCP Integration

This project uses Nautex Model-Context-Protocol (MCP). Nautex manages requirements and task-driven LLM assisted development.
 
Whenever user requests to operate with nautex, the following applies: 

- read full Nautex workflow guidelines from `.nautex/CLAUDE.md`
- note that all paths managed by nautex are relative to the project root
- note primary workflow commands: `nautex__next_scope`, `nautex__tasks_update` 
- NEVER edit files in `.nautex` directory

# Agent Gateway Adapters

See [AGENTS.md](src/nautex/gateway/adapters/AGENTS.md) for credential sandboxing rules and per-agent engineering notes.

<!-- NAUTEX_SECTION_END -->
