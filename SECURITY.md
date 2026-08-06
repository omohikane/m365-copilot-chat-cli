# Security Policy

## Reporting a vulnerability

If you find a security issue, do not open a public issue. Report it privately
by contacting the maintainers directly (e.g. via a private email or GitHub's
private vulnerability reporting), and include:

- a description of the issue
- the affected version
- reproduction steps or a minimal example
- impact / suggested fix, if known

You can expect an acknowledgement and a timeline for a fix. Please give us
time to release a fix before public disclosure.

## Security considerations for this tool

m365-copilot-chat-cli (CLI: `copilot-cli`) controls a real, logged-in M365 Copilot session by reusing a
persistent Chrome profile. Keep the following in mind:

- **SSO session reuse.** The tool launches Chrome with the persistent profile
  at `~/.copilot-cli/chrome-profile`. That profile holds a live corporate SSO
  session. Treat it as a credential: do not commit it, back it up only on
  trusted disks, and do not copy it to shared machines.
- **Conversation logs.** `--once`/`--listen` sessions are written under
  `log/` (gitignored). Review the files before sharing or committing anything,
  since Copilot answers can contain confidential material.
- **Remote control surface.** The MCP server (`copilot-cli mcp`) starts a
  browser per call. Only expose it to MCP clients you trust; a local stdio
  transport is intended.
- **No auto-execution.** Code blocks run only after explicit confirmation
  (`!run` / `!sh`). This is by design and must not be changed to silent
  execution.