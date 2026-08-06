"""Playwright-based agent that drives M365 Copilot.

- Launches system Chrome (persistent profile) and reuses the SSO login
- Sends successive messages on the same tab (no reload)
- Send -> wait for completion (busy indicator + timeout) -> extract answer

SELECTORS are placeholders; reflect real values after DOM investigation
(TODO Phase 3).
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

import config

_SEND_RETRY_WAIT = 0.5  # retry interval for clicking send (seconds)
_POLL_INTERVAL = 0.5  # polling interval while waiting for completion (seconds)


@dataclass
class CodeBlock:
    """One fenced code block from markdown."""

    language: str
    content: str

    def __str__(self) -> str:
        return self.content


def _parse_coded_editor(text: str) -> CodeBlock | None:
    """Rebuild code from a code-editor widget's text.

    Format: line 1 = language name, followed by repeated
    "line-number line / code line". Strip the line numbers
    (lines that are integers only) and return a CodeBlock.
    """
    lines = text.splitlines()
    if not lines:
        return None
    lang = lines[0].strip() or "text"
    code: list[str] = []
    for ln in lines[1:]:
        if ln.strip().isdigit():
            continue
        code.append(ln.rstrip())
    content = "\n".join(code).strip("\n")
    if not content:
        return None
    return CodeBlock(language=lang, content=content)


def _table_rows_to_markdown(rows: list[list[str]]) -> str:
    """Convert an HTML table cell array (rows) to markdown table notation."""
    if not rows:
        return ""
    ncols = max((len(r) for r in rows), default=0)
    if ncols == 0:
        return ""
    padded = [r + [""] * (ncols - len(r)) for r in rows]
    esc = lambda c: str(c).replace("|", "\\|").replace("\n", " ").strip()
    lines: list[str] = ["| " + " | ".join(esc(c) for c in padded[0]) + " |"]
    lines.append("|" + "|".join("---" for _ in range(ncols)) + "|")
    for r in padded[1:]:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)


_TABLE_SEPARATOR = re.compile(r"^\|?\s*[\s:\-|]+\|[\s:\-|]*$")


def _looks_like_markdown_table(text: str) -> bool:
    """Quick check for a markdown table in a string (a `|---` separator row exists)."""
    return any(_TABLE_SEPARATOR.match(ln.strip()) for ln in text.splitlines())


class CopilotAgent:
    """Handles sending/receiving messages to M365 Copilot chat."""

    START_RETRIES = 3
    _STALE_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")

    def __init__(self, headless: bool | None = None) -> None:
        self.headless = headless if headless is not None else (not config.HEADED)
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._last_answer: str = ""
        self._last_code_blocks: list[CodeBlock] = []
        self._last_tables: list[str] = []

    @classmethod
    def _cleanup_stale_profile(cls) -> None:
        """Kill leftover Chrome holding this profile and remove stale singleton locks."""
        try:
            subprocess.run(
                ["pkill", "-9", "-f", str(config.USER_DATA_DIR)],
                capture_output=True,
            )
        except OSError:
            pass
        for name in cls._STALE_LOCK_FILES:
            try:
                (config.USER_DATA_DIR / name).unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------ startup
    def start(self) -> None:
        """Launch system Chrome with a persistent profile and open the chat page.

        Retries up to START_RETRIES times after cleaning up leftover processes.
        """
        for attempt in range(1, self.START_RETRIES + 1):
            self._cleanup_stale_profile()
            try:
                self._pw = sync_playwright().start()
                self._context = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(config.USER_DATA_DIR),
                    channel="chrome",
                    headless=self.headless,
                    args=["--start-maximized"],
                    no_viewport=True,
                )
                self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
                self.page.goto(
                    config.CHAT_URL,
                    wait_until="domcontentloaded",
                    timeout=config.TIMEOUT_SEC * 1000,
                )
                return
            except Exception as exc:
                self._shutdown()
                if attempt == self.START_RETRIES:
                    raise RuntimeError(
                        f"ブラウザ起動に{self.START_RETRIES}回失敗しました（最終エラー: {exc}）"
                    ) from exc
                time.sleep(2)

    def is_logged_in(self) -> bool:
        """Return True if logged in; return False if it cannot be determined."""
        assert self.page is not None
        for selector in config.SELECTORS["login_check"]:
            try:
                if self.page.locator(selector).first.is_visible(timeout=2000):
                    return True
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return False

    def wait_for_login(self, timeout: float = 300.0) -> bool:
        """Wait for the user to finish logging in on the browser (manual SSO assumed)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_logged_in() or self._chat_page_ready():
                return True
            time.sleep(1.0)
        return False

    def _chat_page_ready(self) -> bool:
        """Return True once the chat input box is available."""
        assert self.page is not None
        for selector in config.SELECTORS["input_box"]:
            try:
                if self.page.locator(selector).first.is_visible(timeout=1500):
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------ send
    def send(self, text: str) -> str:
        """Send a prompt and return the answer body (markdown).

        Raises RuntimeError when the operation cannot proceed, e.g. not
        logged in or selector mismatch.
        """
        assert self.page is not None
        self._fill_input(text)
        self._submit()
        self._wait_for_done()
        self._extract_latest_answer(text)
        return self._last_answer

    def _input_locator(self):
        assert self.page is not None
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            for selector in config.SELECTORS["input_box"]:
                locator = self.page.locator(selector).first
                try:
                    if locator.is_visible(timeout=800):
                        return locator
                except Exception:
                    continue
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError("送信ボックスが見つかりません。SELECTORS の確認が必要です（TODO Phase 3）")

    def _fill_input(self, text: str) -> None:
        locator = self._input_locator()
        try:
            locator.click(timeout=3000)
            locator.press("Control+A")
            locator.press("Backspace")
            locator.type(text)
        except Exception as exc:
            raise RuntimeError(f"入力欄への文字入力に失敗しました: {exc}")

    def _generation_started(self, initial: int) -> bool:
        """Return True if sending actually started (busy appears or answer count grew)."""
        assert self.page is not None
        if self._count_answers() > initial:
            return True
        busy = self._first_busy_locator()
        return busy is not None and busy.is_visible()

    def _composer_empty(self) -> bool:
        """Return True if the input box is empty (cleared after submit)."""
        try:
            box = self._input_locator()
            return not (box.inner_text() or "").strip()
        except RuntimeError:
            return False

    def _submitted(self, initial: int) -> bool:
        """Return True if the Enter submit went through (cleared or generation started)."""
        return self._composer_empty() or self._generation_started(initial)

    def _submit(self) -> None:
        """Try Enter to submit; fall back to clicking the send button if needed."""
        assert self.page is not None
        initial = self._count_answers()

        # 1) submit with Enter
        box = self._input_locator()
        box.press("Enter")
        if self._wait_submitted(initial, timeout=8.0):
            return

        # 2) fallback: if text remains in the input box, click the send button
        if not self._composer_empty():
            self._click_send_button()
            if self._wait_submitted(initial, timeout=6.0):
                return

        raise RuntimeError("メッセージの送信が開始されませんでした。SELECTORS の確認が必要です（TODO Phase 3）")

    def _wait_submitted(self, initial: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._submitted(initial):
                return True
            time.sleep(_POLL_INTERVAL)
        return False

    def _click_send_button(self) -> None:
        assert self.page is not None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            for selector in config.SELECTORS["send_button"]:
                locator = self.page.locator(selector).first
                try:
                    if locator.is_visible(timeout=800):
                        locator.click(timeout=2000)
                        return
                except Exception:
                    continue
            time.sleep(_SEND_RETRY_WAIT)
        raise RuntimeError("送信ボタンが見つかりません。SELECTORS の確認が必要です（TODO Phase 3）")

    def _wait_for_done(self) -> None:
        """Wait until the answer completes.

        Completion is judged by the conversation text no longer changing
        (while the busy indicator is hidden). A robust method that does not
        depend on the presence of markdown-reply or the busy indicator.
        """
        assert self.page is not None
        conv = self._conversation_locator()
        busy = self._first_busy_locator()
        previous = conv.inner_text(timeout=5000)
        deadline = time.monotonic() + config.ANSWER_TIMEOUT_SEC
        stable = 0
        while time.monotonic() < deadline:
            current = conv.inner_text(timeout=5000)
            busy_visible = busy is not None and busy.is_visible()
            if current == previous and current:
                if not busy_visible:
                    stable += 1
                    if stable >= 2:
                        self.page.wait_for_timeout(800)
                        return
                else:
                    stable = 0
            else:
                stable = 0
            previous = current
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError(f"回答待ちが {config.ANSWER_TIMEOUT_SEC} 秒を超えました")

    def _conversation_locator(self):
        assert self.page is not None
        for selector in config.SELECTORS["conversation"]:
            locator = self.page.locator(selector).first
            try:
                if locator.count() > 0:
                    return locator
            except Exception:
                continue
        raise RuntimeError("会話コンテナが見つかりません。SELECTORS の確認が必要です（TODO Phase 3）")

    def _first_busy_locator(self):
        assert self.page is not None
        for selector in config.SELECTORS["busy_indicator"]:
            locator = self.page.locator(selector).first
            try:
                if locator.count() > 0 or locator.is_visible(timeout=500):
                    return locator
            except Exception:
                continue
        return None

    # ---------------------------------------------------------------- extract
    def _count_answers(self) -> int:
        assert self.page is not None
        for selector in config.SELECTORS["answer"]:
            try:
                count = self.page.locator(selector).count()
                if count > 0:
                    return count
            except Exception:
                continue
        return 0

    def _clean_reply_text(self, locator) -> str:
        """Get the answer element's text and strip citation/attribution UI fragments.

        Returns flattened plain text. Items removed include the citation button
        (.fai-BebopCitation) and search-linked attribution such as "Powered by ...".
        """
        text = locator.evaluate("""(el) => {
          const clone = el.cloneNode(true);
          clone.querySelectorAll(
            ".fai-BebopCitation, [class*='Citation' i], [class*='attribution' i], " +
            "[aria-label*='Powered by' i]"
          ).forEach(n => n.remove());
          return (clone.innerText || clone.textContent || '').trim();
        }""")
        # normalize newlines and collapse blank lines into single empty lines
        lines = [ln.strip() for ln in text.splitlines()]
        cleaned = "\n".join(lines)
        cleaned = cleaned.replace("\xa0", " ").replace("Show more lines", "")
        return cleaned.strip("\n")

    def _extract_widget_blocks(self) -> list[CodeBlock]:
        """Extract code from code-editor widgets (no ``` fences)."""
        assert self.page is not None
        blocks: list[CodeBlock] = []
        for sel in [".fai-CodeEditor", "[class*='code' i]"]:
            els = self.page.locator(sel)
            try:
                for i in range(els.count()):
                    txt = els.nth(i).inner_text(timeout=2000)
                    parsed = _parse_coded_editor(txt)
                    if parsed and parsed.content not in [b.content for b in blocks]:
                        blocks.append(parsed)
                if blocks:
                    break
            except Exception:
                continue
        return blocks

    def _extract_tables(self) -> list[str]:
        """Extract tables from the answer as markdown tables.

        1) real-DOM `<table>` elements (when Copilot returns a native table)
        2) code-widget blocks whose source is markdown/table
        Collected and returned with duplicates removed.
        """
        assert self.page is not None
        tables: list[str] = []
        for selector in config.SELECTORS["answer"]:
            root = self.page.locator(selector).last
            if root.count() == 0:
                continue
            try:
                for ti in range(root.locator("table").count()):
                    rows = root.locator("table").nth(ti).evaluate(
                        "(t)=>[...t.querySelectorAll('tr')].map("
                        "tr=>[...tr.querySelectorAll('th,td')].map(c=>c.innerText.trim()))"
                    )
                    md = _table_rows_to_markdown(rows)
                    if md and md not in tables:
                        tables.append(md)
            except Exception:
                pass
            break
        for b in self._last_code_blocks:
            if _looks_like_markdown_table(b.content) and b.content not in tables:
                tables.append(b.content.strip("\n"))
        return tables

    def _extract_latest_answer(self, prompt: str = "") -> None:
        """Extract the latest Copilot answer.

        1) prefer the tail of the `answer` element (markdown-reply).
        2) otherwise, pull the string right after the given prompt from the
           whole conversation text (generic fallback).
        """
        assert self.page is not None
        for selector in config.SELECTORS["answer"]:
            locator = self.page.locator(selector)
            try:
                if locator.count() > 0:
                    text = self._clean_reply_text(locator.last)
                    if text:
                        self._last_answer = text
                        blocks = extract_code_blocks(text)
                        for b in self._extract_widget_blocks():
                            if b.content not in [x.content for x in blocks]:
                                blocks.append(b)
                        self._last_code_blocks = blocks
                        self._last_tables = self._extract_tables()
                        return
            except Exception:
                continue

        # fallback: extract the text right after the prompt from the full conversation
        try:
            conv = self._conversation_locator()
            full = conv.inner_text(timeout=3000)
            idx = full.rfind(prompt) if prompt else -1
            text = full[idx + len(prompt):].strip() if idx >= 0 else full
            if text:
                self._last_answer = text
                self._last_code_blocks = extract_code_blocks(text)
                return
        except Exception:
            pass
        raise RuntimeError("回答を抽出できませんでした。SELECTORS の確認が必要です（TODO Phase 3）")

    @property
    def last_code_blocks(self) -> list[CodeBlock]:
        return self._last_code_blocks

    @property
    def last_tables(self) -> list[str]:
        return self._last_tables

    # ---------------------------------------------------------------- model
    def _model_selector_locator(self):
        assert self.page is not None
        deadline = time.monotonic() + 10.0
        for selector in config.SELECTORS["model_selector"]:
            loc = self.page.locator(selector).first
            while time.monotonic() < deadline:
                try:
                    if loc.count() > 0 and loc.is_visible(timeout=600):
                        return loc
                except Exception:
                    pass
                time.sleep(_POLL_INTERVAL)
        return None

    def current_model(self) -> str:
        """Return the selected model's label (the SelectLabel as-is)."""
        sel = self._model_selector_locator()
        if sel is None:
            return ""
        try:
            return (sel.inner_text() or "").strip()
        except Exception:
            return ""

    def list_models(self) -> list[str]:
        """Enumerate the model-selector menu candidates (opens and closes the menu)."""
        assert self.page is not None
        sel = self._model_selector_locator()
        if sel is None:
            raise RuntimeError("モデルセレクタが見つかりません。SELECTORS の確認が必要です（TODO Phase 3）")
        self._open_model_menu()
        items = self._menuitems()
        self.page.keyboard.press("Escape")  # close the menu
        return items

    def _norm(self, txt: str) -> str:
        """Normalize a menuitem's multi-line label into one line (e.g. 'GPT\\nOpenAI' -> 'GPT OpenAI')."""
        return " ".join((txt or "").split())

    def _wait_menuitems(self, timeout: float = 6.0) -> None:
        """Wait for the model menu to open and candidates to appear."""
        assert self.page is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for selector in config.SELECTORS["model_item"]:
                try:
                    if self.page.locator(selector).count() > 0:
                        return
                except Exception:
                    pass
            time.sleep(_POLL_INTERVAL)

    def _open_model_menu(self, attempts: int = 3) -> None:
        """Open the model menu (close first and retry on failure)."""
        for _ in range(attempts):
            self.page.keyboard.press("Escape")  # close any unwanted menu
            self.page.wait_for_timeout(300)
            sel = self._model_selector_locator()
            if sel is None:
                return
            try:
                sel.click(timeout=2000)
            except Exception:
                pass
            if self._wait_menuitems(timeout=4.0):
                return

    def _menuitems(self) -> list[str]:
        assert self.page is not None
        result: list[str] = []
        for selector in config.SELECTORS["model_item"]:
            els = self.page.locator(selector)
            try:
                for i in range(els.count()):
                    txt = self._norm(els.nth(i).inner_text())
                    if txt and txt not in result:
                        result.append(txt)
                if result:
                    break
            except Exception:
                continue
        return result

    def select_model(self, name: str) -> str:
        """Select a model by name and return the selected model name."""
        assert self.page is not None
        sel = self._model_selector_locator()
        if sel is None:
            raise RuntimeError("モデルセレクタが見つかりません。SELECTORS の確認が必要です（TODO Phase 3）")
        target = " ".join(name.strip().lower().split())
        self._open_model_menu()
        candidates = self._menuitems()
        for selector in config.SELECTORS["model_item"]:
            els = self.page.locator(selector)
            try:
                for i in range(els.count()):
                    txt = self._norm(els.nth(i).inner_text())
                    if target in txt.lower():
                        els.nth(i).click(timeout=3000)
                        self.page.wait_for_timeout(600)
                        return txt
            except Exception:
                continue
        self.page.keyboard.press("Escape")
        raise RuntimeError(f"モデル '{name}' が見つかりません。候補: {', '.join(candidates)}")

    def get_thread_text(self) -> list[tuple[str, str]]:
        """Return the current thread as a list of (role, body) pairs.

        role is "user" or "assistant".
        """
        assert self.page is not None
        for selector in ["[data-testid='MessageListContainer']"] + config.SELECTORS["conversation"]:
            root = self.page.locator(selector).last
            if root.count() == 0:
                continue
            try:
                pairs = root.evaluate(
                    """(el)=>{
                      const out=[];
                      el.querySelectorAll('[data-testid="chatQuestion"], [data-testid="markdown-reply"]')
                        .forEach(n=>{
                          const role = n.getAttribute('data-testid')==='chatQuestion' ? 'user':'assistant';
                          const t = n.innerText.trim();
                          if(t) out.push([role,t]);
                        });
                      return out;
                    }"""
                )
            except Exception:
                continue
            if pairs:
                cleaned: list[tuple[str, str]] = []
                for role, content in pairs:
                    content = re.sub(r"^(You said|Copilot said):\s*", "", content, flags=re.I)
                    cleaned.append((role, content))
                return cleaned
            break
        return []

    # ---------------------------------------------------------------- conversation ops
    def new_conversation(self) -> None:
        """Open the chat page in a new tab for a fresh conversation and switch to it."""
        assert self._context is not None
        page = self._context.new_page()
        page.goto(config.CHAT_URL, wait_until="domcontentloaded", timeout=config.TIMEOUT_SEC * 1000)
        self.page = page
        self._last_answer = ""
        self._last_code_blocks = []
        self._last_tables = []

    # ------------------------------------------------------------------ thread restore
    _NAV_FUNCTIONAL = {
        "new chat", "search", "library", "new agent", "more agents",
        "search chats", "prompt gallery", "settings", "export", "agents",
        "researcher", "analyst", "excel", "planner",
    }

    def _ensure_thread_panel(self) -> None:
        """Expand the left nav and scroll until the past-thread list is visible."""
        assert self.page is not None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                nav = self.page.locator("button[aria-label='Expand navigation']")
                if nav.count():
                    nav.first.click(timeout=3000)
                    break
            except Exception:
                pass
            time.sleep(1.0)
        try:
            self.page.evaluate(
                "()=>document.querySelectorAll('*').forEach("
                "e=>{try{if(e.scrollHeight>e.clientHeight+20)"
                "e.scrollTop=e.scrollHeight;}catch(_){}})"
            )
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    def _thread_titles(self) -> list[str]:
        assert self.page is not None
        got: list[str] = []
        seen: set[str] = set()
        links = self.page.locator("a")
        for i in range(links.count()):
            try:
                txt = (links.nth(i).inner_text(timeout=1500).strip() or "").splitlines()[0]
            except Exception:
                continue
            if not txt:
                continue
            norm = txt.lower().replace(", pinned", "").strip()
            if norm in self._NAV_FUNCTIONAL:
                continue
            if txt not in seen:
                seen.add(txt)
                got.append(txt)
        return got

    def list_threads(self, limit: int = 40) -> list[str]:
        """Return past thread titles from the sidebar, newest first."""
        self._ensure_thread_panel()
        deadline = time.monotonic() + 8.0
        titles: list[str] = []
        while time.monotonic() < deadline:
            titles = self._thread_titles()
            if titles:
                break
            time.sleep(1.0)
        return titles[:limit]

    def resume_thread(self, title: str) -> bool:
        """Select and open a past thread from the sidebar by title."""
        self._ensure_thread_panel()
        assert self.page is not None
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            links = self.page.locator("a")
            for i in range(links.count()):
                try:
                    t = (links.nth(i).inner_text(timeout=1500).strip() or "").splitlines()[0]
                except Exception:
                    continue
                if t == title or (t and t.startswith(title)):
                    matched = links.nth(i)
                    matched.click(timeout=5000)
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    deadline = time.monotonic() + 25.0
                    while time.monotonic() < deadline:
                        cq = self.page.locator("[data-testid='chatQuestion']").count()
                        cr = self.page.locator("[data-testid='markdown-reply']").count()
                        if cq or cr:
                            break
                        time.sleep(1.0)
                    self._last_answer = ""
                    self._last_code_blocks = []
                    self._last_tables = []
                    return True
            time.sleep(1.0)
        return False

    # ---------------------------------------------------------------- shutdown
    def _shutdown(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def close(self) -> None:
        self._shutdown()


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """Extract fenced code blocks (```...```) from markdown."""
    blocks: list[CodeBlock] = []
    pattern = re.compile(r"```([\w+-]*)\s*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(text):
        language = match.group(1).strip() or "text"
        content = match.group(2).strip("\n")
        if content:
            blocks.append(CodeBlock(language=language, content=content))
    return blocks