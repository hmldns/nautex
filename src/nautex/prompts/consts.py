

CMD_NAUTEX_SETUP = 'uvx nautex setup'

NAUTEX_SECTION_START = '<!-- NAUTEX_SECTION_START -->'
NAUTEX_SECTION_END = '<!-- NAUTEX_SECTION_END -->'

NAUTEX_RULES_REFERENCE_CONTENT = """# Nautex MCP Integration

This project uses Nautex Model-Context-Protocol (MCP). Nautex manages requirements and task-driven LLM assisted development.
 
Whenever user requests to operate with nautex, the following applies: 

- read full Nautex workflow guidelines from `.nautex/CLAUDE.md`
- note that all paths managed by nautex are relative to the project root
- note primary workflow commands: `next_scope`, `tasks_update` 
- NEVER edit files in `.nautex` directory

"""

DEFAULT_RULES_TEMPLATE = """# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

"""
