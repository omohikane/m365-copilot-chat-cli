# m365-copilot-chat-cli

A CLI/REPL tool that drives M365 Copilot chat (corporate `https://m365.cloud.microsoft/chat/conversation`) by reusing the session of an already-logged-in system Chrome.

See [DESIGN.md](DESIGN.md) for the design and [TODO.md](TODO.md) for progress.

## Setup

```bash
uv sync
uv run python app.py
```

## Using from the CLI (non-interactive, for agents)

`copilot-cli` is a console entry point callable from any directory (installed to `.venv/bin/` via `uv sync`).

```bash
copilot-cli --once 'question'                # send once, print the answer to stdout
echo question | copilot-cli --once -          # read the prompt from stdin
copilot-cli --once 'question' --json --no-log # JSON output (for other agents)
printf 'q1\nq2\n' | copilot-cli --listen --json  # continuous conversation on one thread
copilot-cli --threads --json             # list past threads
copilot-cli --resume 0 --json            # open a past thread (best effort)
```

The `--once` JSON is `{prompt, answer, code_blocks, log_path}`. On failure it returns `{ok: false, error}` with exit code 1.

## Usage (under design/implementation)

- `!run` — confirm and run the latest code block (extracts both fenced and code-editor-widget forms)
- `!save <name>` — save the latest answer as a standalone markdown file
- `!new` — open a new conversation thread
- `!threads` — list past threads
- `!resume <index|name>` — open a past thread (best effort, depends on the sidebar)
- `!save all [name]` — save the whole current thread to `log/`
- `!model <name>` — select a model (e.g. `!model GPT` / `!model Claude`)
- `!models` — list available models and the current display mode
- `!headless` / `!headed` — switch display mode
- `!quit` — exit