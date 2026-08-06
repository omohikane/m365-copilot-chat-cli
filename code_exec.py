"""Execution of code blocks (`!run`).

Per the design (DESIGN.md §7), code runs **only after explicit target
confirmation by the user**. There is no automatic, silent, or
ungated execution.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Callable

import config
from copilot_agent import CodeBlock

#: Language tags excluded from execution (assumed text-only)
NON_EXECUTABLE = {
    "text", "plaintext", "txt", "markdown", "md", "mdx",
    "html", "css", "json", "jsonc", "yaml", "yml", "xml",
    "sql", "csv", "tsv", "log", "diff", "dockerfile",
}


def build_command(block: CodeBlock, python: str | None = None) -> list[str]:
    """Build a run command based on the code block's language."""
    lang = (block.language or "text").lower()
    interpreter = python or sys.executable
    if lang in ("python", "py", "python3"):
        return [interpreter, "-c", block.content]
    if lang in ("bash", "sh", "zsh"):
        return [lang, "-c", block.content]
    if lang == "powershell":
        return ["powershell", "-c", block.content]
    if lang in ("js", "javascript"):
        return ["node", "-e", block.content]
    # Unknown language: do not run python (raise an explicit dummy error)
    return [interpreter, "-c", "raise SystemExit('未対応の言語です')"]


def _is_executable(lang: str) -> bool:
    return lang not in NON_EXECUTABLE or lang in ("bash", "sh", "zsh", "python", "py", "python3", "js", "javascript", "powershell")


def run_shell_command(
    command: str,
    prompt: Callable[[str], str] = input,
    timeout: float | None = None,
) -> str | None:
    """Run an arbitrary local shell command after target confirmation (for `!sh`).

    Even a command typed explicitly by the user goes through the confirmation
    gate to prevent accidental execution.
    """
    print("===== [!sh] 実行対象 =====")
    print(command)
    print("==========================")
    reply = (prompt("このシェルコマンドを実行しますか? [y/N] ") or "").strip().lower()
    if reply not in ("y", "yes"):
        print("[!sh] 実行を中止しました。")
        return None
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout or config.TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return f"[!sh] 実行が {config.TIMEOUT_SEC} 秒を超えました"
    parts = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr}")
    return "\n".join(parts) if parts else "(出力なし)"


def confirm_and_run(
    block: CodeBlock,
    prompt: Callable[[str], str] = input,
    timeout: float | None = None,
) -> str | None:
    """Run the code after target confirmation and return the result string.

    Returns None if the user rejects or the code cannot run.
    """
    lang = (block.language or "text").lower()
    if not _is_executable(lang):
        print(f"[!run] 言語 '{block.language or '(未指定)'}' は直接実行できません。")
        return None

    print("===== 実行対象コード =====")
    print(f"言語: {block.language or '(未指定)'}")
    print(block.content)
    print("==========================")
    reply = (prompt("このコードを実行しますか? [y/N] ") or "").strip().lower()
    if reply not in ("y", "yes"):
        print("[!run] 実行を中止しました。")
        return None

    cmd = build_command(block)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or config.TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        return f"[!run] 実行環境が見つかりません: {exc.filename}"
    except subprocess.TimeoutExpired:
        return f"[!run] 実行が {config.TIMEOUT_SEC} 秒を超えました"

    parts = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr}")
    if not parts:
        return "(出力なし)"
    return "\n".join(parts)