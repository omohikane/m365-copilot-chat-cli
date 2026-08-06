"""Append-only markdown log and `!save` artifact persistence.

Files are written under `config.LOG_DIR` (`./log`), which is gitignored.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import config


def _sanitize(name: str, maxlen: int = 30) -> str:
    """Return a filename-safe string with characters that are invalid in paths replaced."""
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "-", name.strip())
    cleaned = cleaned.strip("-.")
    if len(cleaned) > maxlen:
        cleaned = cleaned[:maxlen]
    return cleaned or "untitled"


class Logger:
    """Append conversation logs to one log file per day."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir or config.LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file: Path | None = None
        self._title = ""

    def _ensure_file(self, title: str) -> Path:
        """Open a new file when the title changes."""
        today = datetime.now().strftime("%Y%m%d")
        filename = f"{today}-{_sanitize(title)}.md"
        path = self.log_dir / filename
        if self._file != path:
            if not path.exists():
                path.write_text(f"# {title}\n\n日付: {datetime.now().isoformat()}\n\n", encoding="utf-8")
            self._file = path
            self._title = title
        return path

    def append_exchange(self, prompt: str, answer: str, meta: str = "") -> Path:
        """Append one exchange (user prompt -> Copilot answer) to the log."""
        path = self._ensure_file(prompt)
        now = datetime.now().strftime("%H:%M:%S")
        lines = [
            f"## [{now}] ユーザー",
            "",
            prompt,
            "",
            "### Copilot",
            "",
            answer,
            "",
        ]
        if meta:
            lines.extend([f"_{meta}_", ""])
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def save(self, title: str, content: str) -> Path:
        """For `!save`: persist the latest answer as a standalone markdown file."""
        safe = _sanitize(title)
        path = self.log_dir / f"{safe}.md"
        body = (
            f"# {title}\n\n"
            f"日付: {datetime.now().isoformat()}\n\n"
            f"---\n\n{content}\n"
        )
        path.write_text(body, encoding="utf-8")
        return path

    def save_thread(self, title: str, turns: list[tuple[str, str]]) -> Path:
        """For `!save all`: persist the whole thread (sequence of Q/A) as a standalone markdown file."""
        safe = _sanitize(title)
        path = self.log_dir / f"{safe}-thread.md"
        lines = [f"# {title}\n", "", f"日付: {datetime.now().isoformat()}\n"]
        for role, content in turns:
            label = "ユーザー" if role == "user" else "Copilot"
            lines += ["", f"## {label}", "", content, ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path