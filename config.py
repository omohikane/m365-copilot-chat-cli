"""Central configuration.

Collects the constants needed at runtime: URLs, paths, selectors, and
timeouts. SELECTORS are placeholders until confirmed by real-DOM
investigation (TODO Phase 3).
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Chat destination ---------------------------------------------------------
CHAT_URL = "https://m365.cloud.microsoft/chat/conversation"

# --- Paths --------------------------------------------------------------------
HOME = Path.home()
USER_DATA_DIR = HOME / ".copilot-cli" / "chrome-profile"  # persistent profile
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "log"

# --- Display mode -------------------------------------------------------------
HEADED = True  # default is headed (to confirm login)

# --- Timeouts -----------------------------------------------------------------
TIMEOUT_SEC = 60.0  # generic timeout (page load, code exec, etc.)
ANSWER_TIMEOUT_SEC = 300.0  # total upper bound for waiting on an answer (incl. busy)

# --- Command defaults ---------------------------------------------------------
DEFAULT_SHELL = os.environ.get("SHELL", "sh")

# --- Selectors (confirmed by real-DOM investigation, Phase 3) -----------------
# Target machine: M365 Copilot (en-GB display). Values confirmed by DOM survey.
SELECTORS: dict[str, list[str]] = {
    # Send box (contenteditable SPAN, role=textbox, aria="Message Copilot")
    "input_box": [
        "[contenteditable='true']",
        "div[role='textbox']",
        "textarea",
    ],
    # Send button (appears once text is entered)
    "send_button": [
        "button[aria-label='Send']",
        "button[aria-label='送信']",
        "button[type='submit']",
    ],
    # Busy indicator (Stop button shown only while generating)
    "busy_indicator": [
        "button[aria-label='Stop generating']",
        "button[aria-label*='Stop' i]",
        "button[aria-label*='停止' ]",
    ],
    # Conversation container
    "conversation": [
        "[data-testid='chatOutput']",
        "main",
    ],
    # User message
    "user_message": [
        "[data-testid='chatQuestion']",
        ".fai-UserMessage",
    ],
    # Copilot answer (markdown-rendered element)
    "answer": [
        "[data-testid='markdown-reply']",
    ],
    # Model selector (menu items appear as [role='menuitem'] after expanding)
    "model_selector": [
        "button[aria-label='Model Selector']",
    ],
    "model_item": [
        "[role='menuitem']",
    ],
    # Login-state check (whether the chat page rendered)
    "login_check": [
        "[data-testid='chatOutput']",
        "[contenteditable='true']",
    ],
}