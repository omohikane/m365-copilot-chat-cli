# Contributing

Thanks for taking the time to contribute to m365-copilot-chat-cli.

## Setup

```bash
git clone <your-fork>
cd m365-copilot-chat-cli
uv sync          # creates .venv and installs console entry `copilot-cli`
```

Requires Python >= 3.10 and a local Google Chrome installation (Playwright
reuses the system Chrome session for SSO).

## Development workflow

1. Create a feature branch: `git checkout -b feat/<name>`
2. Make changes. Python is the only language; follow the existing style
   (comments and docstrings in English; user-facing strings are kept in
   Japanese).
3. Sanity-check everything compiles:

   ```bash
   uv run python -m py_compile app.py config.py copilot_agent.py logger.py \
       code_exec.py mcp_server.py tools/dom_inspect.py
   ```

4. Smoke-test the CLI help without touching a browser:

   ```bash
   copilot-cli --help
   ```

5. Commit in meaningful units (one logical change per commit).
6. Open a pull request.

## Running against the real M365 Copilot

The tool drives a logged-in M365 Copilot via Playwright. Browser operations
launch a Chrome profile under `~/.copilot-cli/chrome-profile`; each tool call
starts a browser, completes, and closes it. This requires an existing,
logged-in session, so local manual verification is expected.

## MCP usage

The `mcp` subcommand exposes the MCP server over stdio. Register it in your
MCP client, e.g. in opencode:

```json
{
  "mcp": {
    "copilot-cli": {
      "type": "local",
      "command": ["<abs>/copilot-chat-cli/.venv/bin/copilot-cli", "mcp"]
    }
  },
  "experimental": { "mcp_timeout": 600000 }
}
```

See the project `AGENTS.md` for the tools and usage notes.