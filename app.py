"""copilot-cli REPL main entry.

Examples:
    uv run python app.py          # launch headed
    uv run python app.py --headless

Commands:
    !run            show the latest code block, then run it after confirmation
    !save <name>    save the latest answer as a standalone markdown file
    !new            open a new conversation tab
    !headless/!headed   switch display mode and restart
    !quit           exit
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass

import config
from code_exec import confirm_and_run, run_shell_command
from copilot_agent import CopilotAgent, CodeBlock, extract_code_blocks
from logger import Logger

_CODE_RE = re.compile(r"```([\w+-]*)\s*\n(.*?)```", re.DOTALL)
_BAR = "=" * 40

C_RESET = "\033[0m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"


def _color(text: str, code: str) -> str:
    """Apply ANSI color only when writing to a terminal (plain when piped/redirected)."""
    if sys.stdout.isatty():
        return f"{code}{text}{C_RESET}"
    return text


def _segments(text: str):
    """Split an answer into body (text) and code segments, yielded in order."""
    pos = 0
    for m in _CODE_RE.finditer(text):
        if m.start() > pos:
            yield ("text", text[pos:m.start()])
        yield ("code", CodeBlock(m.group(1) or "text", m.group(2)))
        pos = m.end()
    if pos < len(text):
        yield ("text", text[pos:])


def print_answer(text: str) -> None:
    """Display an answer split into body and code blocks for readability."""
    segs = list(_segments(text))
    if not any(kind == "code" for kind, _ in segs):
        print(_color(text.strip(), C_GREEN))
        return
    idx = 0
    for kind, content in segs:
        if kind == "text":
            if content.strip():
                print(_color(content.strip(), C_GREEN))
                print()
        else:
            idx += 1
            bar = _color(_BAR, C_CYAN)
            print(bar)
            print(_color(f" [コードブロック {idx}] 言語: {content.language}", C_CYAN + C_BOLD))
            print(bar)
            print(content.content.rstrip())
            print(bar)
            print()
    print(_color("[!run] で直近のコードを確認実行できます。", C_YELLOW))


@dataclass
class OnceResult:
    """Return value of a non-interactive run. Used by other agents/scripts."""

    prompt: str
    answer: str
    code_blocks: list[dict]
    log_path: str | None = None


def run_once(prompt: str, headless: bool = True, save_log: bool = True) -> OnceResult:
    """Send a single prompt and get the answer (non-interactive, callable entry).

    The browser is started only during the run and closed afterwards.
    """
    logger = Logger()
    agent = CopilotAgent(headless=headless)
    agent.start()
    try:
        if not agent.is_logged_in():
            agent.wait_for_login(timeout=300)
        answer = agent.send(prompt)
    finally:
        agent.close()
    blocks = [
        {"language": b.language, "content": b.content}
        for b in agent.last_code_blocks
    ]
    result = OnceResult(prompt=prompt, answer=answer, code_blocks=blocks, log_path=None)
    if save_log:
        try:
            path = logger.append_exchange(prompt, answer, meta="run_once")
            result.log_path = str(path)
        except OSError:
            pass
    return result


_KNOWN_FLAGS = {"--once", "--headless", "--headed", "--json", "--no-log",
                "--threads", "--resume", "--listen", "--help", "-h"}


def _run_listen(argv: list[str]) -> int:
    """Read prompts one per line from stdin and converse in the same browser/thread.

    The session is kept across the whole run, so context carries over between
    turns. With --json, prints one JSON object per line (NDJSON) to stdout.
    """
    headless = "--headed" not in argv
    json_out = "--json" in argv
    save_log = "--no-log" not in argv
    if sys.stdin.isatty():
        print("[info] --listen: stdinから質問を1行ずつ読み込みます（Ctrl-Dで終了）")
    logger = Logger()
    agent = CopilotAgent(headless=headless)
    try:
        agent.start()
        if not agent.is_logged_in():
            agent.wait_for_login(timeout=300)
        for line in sys.stdin:
            prompt = line.strip()
            if not prompt:
                continue
            if prompt in ("!quit", "!exit"):
                break
            try:
                answer = agent.send(prompt)
            except RuntimeError as exc:
                if json_out:
                    print(json.dumps({"ok": False, "prompt": prompt, "error": str(exc)}, ensure_ascii=False), flush=True)
                else:
                    print(_color(f"[error] {exc}", C_RED), flush=True)
                continue
            blocks = [
                {"language": b.language, "content": b.content}
                for b in agent.last_code_blocks
            ]
            if save_log:
                try:
                    logger.append_exchange(prompt, answer, meta="listen")
                except OSError:
                    pass
            if json_out:
                print(json.dumps({"ok": True, "prompt": prompt, "answer": answer, "code_blocks": blocks}, ensure_ascii=False), flush=True)
            else:
                print("-----", flush=True)
                print(answer, flush=True)
    finally:
        agent.close()
    return 0


def _resolve_thread_target(arg: str, agent: CopilotAgent) -> str:
    try:
        n = int(arg)
        titles = agent.list_threads(limit=40)
        if 0 <= n < len(titles):
            return titles[n]
        raise ValueError(arg)
    except ValueError:
        return arg


def _run_threads(argv: list[str]) -> int:
    headless = "--headed" not in argv
    json_out = "--json" in argv
    try:
        agent = CopilotAgent(headless=headless)
        agent.start()
        try:
            if not agent.is_logged_in():
                agent.wait_for_login(timeout=300)
            titles = agent.list_threads(limit=40)
        finally:
            agent.close()
    except RuntimeError as exc:
        if json_out:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(_color(f"[error] {exc}", C_RED))
        return 1
    if json_out:
        print(json.dumps({"threads": titles}, ensure_ascii=False, indent=2))
    else:
        if not titles:
            print("(過去スレッドなし)")
        for i, t in enumerate(titles):
            print(f"[{i}] {t}")
    return 0


def _run_resume(argv: list[str]) -> int:
    i = argv.index("--resume")
    if i + 1 >= len(argv):
        print("[error] --resume には番号または名前が必要です。例: copilot-cli --resume 0")
        return 2
    arg = argv[i + 1]
    headless = "--headed" not in argv
    json_out = "--json" in argv
    try:
        agent = CopilotAgent(headless=headless)
        agent.start()
        try:
            if not agent.is_logged_in():
                agent.wait_for_login(timeout=300)
            target = _resolve_thread_target(arg, agent)
            ok = agent.resume_thread(target)
        finally:
            agent.close()
    except RuntimeError as exc:
        if json_out:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(_color(f"[error] {exc}", C_RED))
        return 1
    if json_out:
        print(json.dumps({"ok": ok, "target": target}, ensure_ascii=False, indent=2))
    else:
        print(f"[resume] {target}: {'開きました' if ok else '見つかりません'}")
    return 0 if ok else 1


def _run_once(argv: list[str]) -> int:
    tail = argv[argv.index("--once") + 1:]
    prompt = " ".join(a for a in tail if a not in _KNOWN_FLAGS).strip()
    if prompt in ("-", ""):
        read = ("" if sys.stdin.isatty() else sys.stdin.read()).strip()
        prompt = read
    if not prompt:
        print("[error] --once にはプロンプトが必要です。例: copilot-cli --once '質問'  /  echo 質問 | copilot-cli --once -")
        return 2
    headless = "--headed" not in argv
    save_log = "--no-log" not in argv
    json_out = "--json" in argv
    try:
        result = run_once(prompt, headless=headless, save_log=save_log)
    except RuntimeError as exc:
        if json_out:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(_color(f"[error] {exc}", C_RED))
        return 1
    if json_out:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(result.answer)
    return 0


def _parse_headless(argv: list[str]) -> bool:
    return "--headless" in argv


def _banner() -> None:
    print("copilot-cli (M365 Copilot CLI)")
    print("コマンド: !help / !run / !sh <cmd> / !save <名前> / !new / !model <名前> / !models / !headless / !headed / !quit")


HELP = """\
使い方
  プロンプトにそのまま文字を打つと M365 Copilot に送信し、回答を表示します。
  回答は log/ 配下に markdown で自動保存されます。

コマンド
  !help            このヘルプを表示
  !models          利用可能モデル一覧と現在の表示モード
  !model <名前>    モデルを選択（例: !model GPT / !model Claude）
  !run             直近のコードブロックを表示して確認後に実行
  !sh <コマンド>   ローカルシェルコマンドを確認後に実行（例: !sh ls -la）
  !save <名前>     直近の回答を log/ に別markdownとして保存
  !new             新しい会話タブを開く
  !threads         過去スレッド一覧
  !resume <番号|名前>  過去スレッドを開く（ベストエフォート）
  !save all        現在スレッドの全文を保存
  !headless        ヘッドレス表示に切り替えて再起動
  !headed          表示付きに切り替えて再起動
  !quit            終了

起動オプション
  copilot-cli                         表示付きで起動
  copilot-cli --headless              非表示で起動
  copilot-cli --help                  このヘルプを表示
  copilot-cli --once '質問'            1回だけ送信して回答をstdoutへ（非対話）
  echo 質問 | copilot-cli --once -    プロンプトをstdinから受ける
  copilot-cli --listen [--json]       同一スレッドで連続会話（stdinに1行1質問）
  copilot-cli --threads [--json]      過去スレッド一覧（非対話）
  copilot-cli --resume 0 [--json]     過去スレッドを開く（非対話）
      --once に指定できる追加フラグ:
        --headless / --headed   表示モード（既定: headless）
        --json                  結果をJSONで出力（他エージェント向け）
        --no-log                ログ保存をしない
"""


def print_help() -> None:
    print(HELP)


def _run_repl(agent: CopilotAgent, logger: Logger) -> None:
    last_answer = ""
    last_blocks: list[CodeBlock] = []
    while True:
        try:
            raw = input(_color("> ", C_CYAN)).strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            continue
        if not raw:
            continue

        if raw == "!quit":
            break
        if raw in ("!help", "!h"):
            print_help()
            continue
        if raw == "!new":
            agent.new_conversation()
            print("[new] 新規会話タブを開きました。")
            continue
        if raw == "!threads":
            try:
                titles = agent.list_threads(limit=40)
            except RuntimeError as exc:
                print(f"[error] {exc}")
                continue
            if not titles:
                print("[threads] 過去スレッドが見つかりません。")
                continue
            for i, t in enumerate(titles):
                print(f"  [{i}] {t}")
            print("[threads] 開くには: !resume <番号|名前>")
            continue
        if raw == "!resume":
            print("[!resume] 使用例: !resume <番号|名前>  （番号は !threads 表示）")
            continue
        if raw.startswith("!resume "):
            arg = raw[len("!resume "):].strip()
            try:
                n = int(arg)
                titles = agent.list_threads(limit=40)
                titles = titles[n:n + 1] if 0 <= n < len(titles) else []
                if not titles:
                    print(f"[error] 番号 {n} に対応するスレッドがありません。")
                    continue
                target = titles[0]
            except ValueError:
                target = arg
            try:
                ok = agent.resume_thread(target)
            except RuntimeError as exc:
                print(f"[error] {exc}")
                continue
            if ok:
                print(f"[resume] スレッドを開きました: {target}（保存は: !save all）")
            else:
                print(f"[resume] スレッドが見つかりません: {target}")
            continue
        if raw == "!save all":
            turns = agent.get_thread_text()
            if not turns:
                print("[!save] 保存する会話がありません（現在のスレッドが空です）。")
                continue
            title = turns[0][1][:30] or "thread"
            path = logger.save_thread(title, turns)
            print(f"[!save] スレッド全文を保存しました: {path}")
            continue
        if raw == "!models":
            try:
                models = agent.list_models()
                cur = agent.current_model()
                print(f"[models] コンポーザー表示: {cur or '(不明)'}")
                print("[models] 利用可能モデル:")
                for m in models:
                    print(f"  - {m}")
            except RuntimeError as exc:
                print(f"[error] {exc}")
            continue
        if raw == "!model":
            print("[!model] 使用例: !model GPT / !model Claude")
            continue
        if raw.startswith("!model "):
            name = raw[len("!model "):].strip()
            try:
                result = agent.select_model(name)
                print(f"[model] 選択しました: {result}")
            except RuntimeError as exc:
                print(f"[error] {exc}")
            continue
        if raw == "!run":
            if not last_blocks:
                print("[!run] 実行対象のコードブロックがありません。")
            else:
                result = confirm_and_run(last_blocks[-1])
                if result is not None:
                    print(result)
            continue
        if raw == "!sh":
            print("[!sh] 使用例: !sh ls -la / !sh echo hello")
            continue
        if raw.startswith("!sh "):
            cmd = raw[len("!sh "):].strip()
            result = run_shell_command(cmd)
            if result is not None:
                print(result)
            continue
        if raw == "!save":
            print("[!save] 名前を指定してください: !save <名前>")
            continue
        if raw.startswith("!save "):
            name = raw[len("!save "):].strip()
            if not last_answer:
                print("[!save] 保存する回答がありません。")
                continue
            path = logger.save(name, last_answer)
            print(f"[!save] 保存しました: {path}")
            continue
        if raw == "!headless":
            print("[mode] headless に切り替えて再起動します。")
            agent.close()
            agent = CopilotAgent(headless=True)
            agent.start()
            continue
        if raw == "!headed":
            print("[mode] headed に切り替えて再起動します。")
            agent.close()
            agent = CopilotAgent(headless=False)
            agent.start()
            continue
        if raw.startswith("!"):
            print(f"不明なコマンド: {raw}")
            continue

        # normal prompt send
        print(_color(raw or "", C_YELLOW))
        try:
            answer = agent.send(raw)
        except RuntimeError as exc:
            print(_color(f"[error] {exc}", C_RED))
            continue
        last_answer = answer
        last_blocks = agent.last_code_blocks
        print("-----")
        print_answer(answer)
        print("-----")
        try:
            path = logger.append_exchange(raw, answer)
            print(f"(ログ: {path})")
        except OSError as exc:
            print(f"[warn] ログ保存に失敗: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        from mcp_server import main as mcp_main
        return mcp_main()
    if any(a in ("--help", "-h") for a in argv):
        print_help()
        return 0
    if "--once" in argv:
        return _run_once(argv)
    if "--threads" in argv:
        return _run_threads(argv)
    if "--resume" in argv:
        return _run_resume(argv)
    if "--listen" in argv:
        return _run_listen(argv)
    headless = _parse_headless(argv)
    logger = Logger()
    _banner()
    print(f"モード: {'headless' if headless else 'headed'}")
    try:
        agent = CopilotAgent(headless=headless)
        agent.start()
    except Exception as exc:
        print(f"[error] Chrome の起動に失敗しました: {exc}")
        print("Chrome が導入されているか、user_data_dir を確認してください。")
        return 1

    if not agent.is_logged_in():
        print("[info] ログイン画面が表示される場合があります。ブラウザでSSOを完了してください。")
        agent.wait_for_login()

    try:
        _run_repl(agent, logger)
    finally:
        agent.close()
    print("終了します。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
