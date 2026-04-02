"""
Telegram sender — PolyMarket Research Bot notifications.

Uses only the Telegram Bot API via HTTP (requests), no extra library needed.

Setup:
  1. Create a bot via @BotFather → get TELEGRAM_BOT_TOKEN
  2. Start a chat with the bot (or add it to a group/channel)
  3. Get your TELEGRAM_CHAT_ID:
     - Personal chat: message @userinfobot
     - Group: add bot to group, send a message, visit
       https://api.telegram.org/bot<TOKEN>/getUpdates and find "chat":{"id":...}
     - Channel: use @ChannelID_bot or prefix with -100 for public channels
"""

import re
import time
from typing import Sequence

import requests

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_MSG_LEN = 4000   # safe limit below Telegram's 4096 cap
_RETRY_DELAY = 2      # seconds between retries on flood control


def _api(token: str, method: str, **kwargs) -> dict:
    url = _TELEGRAM_API.format(token=token, method=method)
    try:
        r = requests.post(url, json=kwargs, timeout=30)
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Markdown → Telegram HTML conversion
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """
    Convert a subset of Markdown to Telegram HTML (parse_mode=HTML).
    Handles: headers, bold, italic, inline code, code blocks, bullet lists.
    """
    # Code blocks (```...```) → <pre><code>
    text = re.sub(
        r"```(?:\w+)?\n?(.*?)```",
        lambda m: f"<pre><code>{_escape(m.group(1).strip())}</code></pre>",
        text, flags=re.DOTALL,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", lambda m: f"<code>{_escape(m.group(1))}</code>", text)

    lines = text.split("\n")
    out = []
    for line in lines:
        # ### H3 → bold
        if re.match(r"^###\s+", line):
            line = "<b>" + _escape(line[4:].strip()) + "</b>"
        # ## H2 → bold + underline feel
        elif re.match(r"^##\s+", line):
            line = "\n<b>▸ " + _escape(line[3:].strip()) + "</b>"
        # # H1 → bold large
        elif re.match(r"^#\s+", line):
            line = "\n<b>━━ " + _escape(line[2:].strip()) + " ━━</b>"
        else:
            # Bold **text**
            line = re.sub(r"\*\*(.+?)\*\*", lambda m: f"<b>{_escape(m.group(1))}</b>", line)
            # Italic *text* (not inside **)
            line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
                          lambda m: f"<i>{_escape(m.group(1))}</i>", line)
            # Bullet - → •
            line = re.sub(r"^(\s*)-\s+", lambda m: m.group(1) + "• ", line)
            # Horizontal rule ---
            if re.match(r"^[-─═]{3,}$", line.strip()):
                line = "─────────────────"
        out.append(line)

    return "\n".join(out)


def _escape(text: str) -> str:
    """Escape HTML special chars for Telegram HTML mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Message chunking
# ---------------------------------------------------------------------------

def _split_message(text: str, max_len: int = _MAX_MSG_LEN) -> list[str]:
    """
    Split a long message into chunks that fit Telegram's limit.
    Tries to split on double newlines (paragraph boundaries) first,
    then on single newlines, then hard-cuts as last resort.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_len:
        # Try paragraph boundary
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut == -1:
            # Try line boundary
            cut = remaining.rfind("\n", 0, max_len)
        if cut == -1:
            # Hard cut
            cut = max_len
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_message(
    token: str,
    chat_id: str,
    text: str,
    markdown: bool = True,
    disable_preview: bool = True,
) -> list[dict]:
    """
    Send a (possibly long) message to a Telegram chat.
    If markdown=True, converts Markdown to Telegram HTML automatically.
    Long messages are automatically split into multiple sends.
    Returns list of API responses (one per chunk).
    """
    if markdown:
        html_text = _md_to_html(text)
        parse_mode = "HTML"
    else:
        html_text = text
        parse_mode = None

    chunks = _split_message(html_text)
    results = []

    for i, chunk in enumerate(chunks):
        params: dict = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode

        resp = _api(token, "sendMessage", **params)
        results.append(resp)

        if not resp.get("ok"):
            err = resp.get("description", "unknown error")
            # Flood control: Telegram may ask us to wait
            if "retry_after" in str(resp):
                retry = int(re.search(r"retry_after[\":\s]+(\d+)", str(resp)).group(1))
                time.sleep(retry + 1)
                resp = _api(token, "sendMessage", **params)
                results[-1] = resp

        # Polite delay between chunks to avoid flood
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return results


def send_report(
    token: str,
    chat_id: str,
    report_text: str,
    header: str | None = None,
) -> bool:
    """
    Send a research report to Telegram.
    Prepends an optional header, converts Markdown, splits if needed.
    Returns True if all chunks sent successfully.
    """
    if header:
        full_text = f"{header}\n\n{report_text}"
    else:
        full_text = report_text

    results = send_message(token, chat_id, full_text)
    return all(r.get("ok") for r in results)


def test_connection(token: str, chat_id: str) -> dict:
    """
    Send a test message to verify bot credentials and chat ID.
    Returns {"ok": True/False, "message": ...}
    """
    resp = _api(token, "getMe")
    if not resp.get("ok"):
        return {"ok": False, "message": f"Invalid bot token: {resp.get('description', 'unknown')}"}

    bot_name = resp.get("result", {}).get("username", "?")
    resp2 = send_message(token, chat_id, f"✅ PolyMarket Research Bot connected! (@{bot_name})", markdown=False)
    if resp2 and resp2[0].get("ok"):
        return {"ok": True, "message": f"Connected as @{bot_name}"}
    return {"ok": False, "message": f"Bot token OK but cannot send to chat_id={chat_id}. "
                                     "Make sure you've started a chat with the bot first."}
