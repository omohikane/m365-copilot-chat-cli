"""Read-only probe for investigating the DOM of the real browser (Phase 3).

Sends no messages. It opens the page and reports the current URL, the
presence of various elements, and whether candidate selectors work, to stdout.

Usage:
    uv run python tools/dom_inspect.py [--headed] [--wait-login] [--dump-detail]
  --headed      launch with a visible window (default is headless)
  --wait-login  wait for login before probing (first-time SSO; default 300 s)
  --dump-detail enumerate data-testid / aria-label (for chat-page survey)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

import config

LOGIN_TIMEOUT = 300.0
READY_MARKERS = [
    "[contenteditable='true']",
    "div[role='textbox']",
    "textarea",
]


def _chat_ready(page) -> bool:
    for sel in READY_MARKERS:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def _wait_login(page) -> None:
    print("(SSOログインを待機します。ブラウザでサインインしてください…)")
    deadline = time.monotonic() + LOGIN_TIMEOUT
    while time.monotonic() < deadline:
        page.wait_for_timeout(1500)
        if _chat_ready(page) or "conversation" in page.url or "chat" in page.url:
            page.wait_for_timeout(2000)
            return
    print("!! ログイン待ちがタイムアウトしました。")


def _report_dom(page) -> None:
    print("URL: ", page.url)
    print("TITLE:", page.title())
    print("=" * 40)

    print("--- editable / inputs ---")
    for sel in READY_MARKERS + [
        "[contenteditable='plaintext-only']",
        "input[type='text']",
        "input[type='search']",
    ]:
        print(f"  {sel!r}: {page.locator(sel).count()}")

    print("--- candidate SELECTORS (config.SELECTORS) ---")
    for key, sels in config.SELECTORS.items():
        for sel in sels:
            print(f"  {key} :: {sel!r}: {page.locator(sel).count()}")

    print("--- contenteditable 試し打ち（入力のみ・送信しない）---")
    for sel in READY_MARKERS:
        n = page.locator(sel).count()
        info = None
        if n:
            loc = page.locator(sel).first
            info = loc.evaluate(
                "el => ({tag: el.tagName, role: el.getAttribute('role'),"
                " aria: el.getAttribute('aria-label'),"
                " ph: el.getAttribute('data-placeholder-id') || el.getAttribute('placeholder')})"
            )
        print(f"  {sel!r}: count={n}, info={info}")


def _report_detail(page) -> None:
    print("=== data-testid 一覧（出現順・重複除く・最大50件）===")
    seen: list[str] = []
    for el in page.locator("[data-testid]").all():
        tid = el.get_attribute("data-testid") or ""
        if tid and tid not in seen:
            seen.append(tid)
    for tid in seen[:50]:
        print("  ", tid)

    print("=== button/aria-label 一覧（最大50件）===")
    for sel in ["button", "[role='button']"]:
        els = page.locator(sel)
        total = min(els.count(), 50)
        for i in range(total):
            aria = els.nth(i).get_attribute("aria-label") or ""
            txt = (els.nth(i).inner_text() or "").strip().replace("\n", " ")
            if aria or txt:
                print(f"  {sel}[{i}] aria={aria!r} text={txt!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-login", action="store_true")
    parser.add_argument("--dump-detail", action="store_true")
    args = parser.parse_args()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(config.USER_DATA_DIR),
            channel="chrome",
            headless=not args.headed,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(config.CHAT_URL, wait_until="domcontentloaded", timeout=config.TIMEOUT_SEC * 1000)
        page.wait_for_timeout(3000)

        if args.wait_login:
            _wait_login(page)
        else:
            page.wait_for_timeout(4000)

        _report_dom(page)
        if args.dump_detail:
            _report_detail(page)

        ctx.close()


if __name__ == "__main__":
    main()
