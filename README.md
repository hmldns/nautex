
This is MCP server that integrates PRD and TRD building tool [Nautex AI](https://nautex.ai) with the conding agents. 

Nautex AI acts as a Product and Project manager for coding agents, speeding up AI assisted development by communicating requirements well.

By [Ivan Makarov](https://x.com/ivan_mkrv)

# Setup

1. Go to the new project folder and run in the terminal:
```bash
uvx nautex setup
```

<details>
<summary>How to Install uv</summary>

On macOS and linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows
```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Check the latest instruction from [UV repo](https://github.com/astral-sh/uv) for details and updates
</details>

You should see the terminal user interface

![Setup Screenshot](doc/setup_screen.png)

2. Follow the guidelines via UI 
 - go [Nautex.ai](https://app.nautex.ai/settings/nautex-api) to sign up and create API token
 - In the web app, create PRD and TRD documents:
   - Chat with the bot for capturing requirements. 
   - After initial documents generation Create files map of the project inside the map.
   - Then, after reviewing resulted map create implementation plan.
   - Go back to the CLI UI
- Select project
- Select implementation plan
- Ensure you've got right MCP config in `.cursor/mcp.json`, manually or via TUI (it will merge with any existing config)

```json
{
  "mcpServers": {
    "nautex": {
      "command": "uvx",
      "args": [
        "nautex",
        "mcp"
      ]
    }
  }
}
```
- Ensure nautex workflow rules are in `.cursor/rules/` folder via TUI command.

3. (Optional) Check MCP server response ```uvx nautex mcp test next_scope```

4. Tell cursor in Agent mode: 
 > Pull nautex rules and proceed to the next scope

5. Proceed with the plan by reviewing progress and supporting the Agent with validation feedback and inputs.

