"""Reply to /start in private Telegram bot chats with Serbia24 channel links.

Run by GitHub Actions (at most every ~5 min, schedule may be delayed).
Only opt-in /start, /channels, /help commands are answered. No broadcasts, no
channel posts, no user ID/name/chat content retained in public repository.
The Afisha bot is checked first; a distinct news bot is checked second.
Does not interfere with channel publisher jobs or modify webhook configuration.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

STATE = Path(__file__).resolve().parents[1] / "data" / "welcome_offsets.json"
MAX_BATCHES = 3
MAX_UPDATES = 100
MAX_AGE_SECONDS = 24 * 3600
COMMAND = re.compile(r"^/([a-zA-Z_]{1,32})(?:@([a-zA-Z0-9_]{3,40}))?(?:\s.*)?$", re.S)

CHANNELS = (
    ("🎭 Сербия 24 | Афиша", "https://t.me/Serbia24Afisha",
     "Концерты, фестивали, спектакли, выставки и семейные мероприятия по всей Сербии."),
    ("📰 Сербия 24 | Новости", "https://t.me/serbia24live",
     "Главные новости Сербии на русском: события, решения, цены и полезные изменения."),
    ("🛍 Барахолка Сербии", "https://t.me/baraholka_serbia",
     "Объявления, покупки и продажи, полезные предложения в Сербии."),
)

WELCOME_TEXT = (
    "🇷🇸 Добро пожаловать в наши каналы о Сербии!\n\n"
    + "\n\n".join(f"{title}\n{description}" for title, _, description in CHANNELS)
    + "\n\n👇 Выберите канал и подпишитесь на интересное!"
)

KEYBOARD = {
    "inline_keyboard": [
        [{"text": label, "url": link}]
        for label, link, _ in CHANNELS
    ]
}


def read_state(path: Path = STATE) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value for key, value in raw.items()
        if isinstance(key, str) and key.isdecimal()
        and type(value) is int and 0 <= value < 2**63
    }


def write_state(state: dict[str, int], path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def command_requested(message: Any, bot_username: str) -> bool:
    if not isinstance(message, dict) or not isinstance(message.get("chat"), dict):
        return False
    if message["chat"].get("type") != "private":
        return False
    if message.get("from", {}).get("is_bot") is True:
        return False
    value = message.get("text")
    if not isinstance(value, str):
        return False
    match = COMMAND.fullmatch(value.strip())
    if not match or match.group(1).lower() not in ("start", "help", "channels"):
        return False
    mention = match.group(2)
    return not mention or mention.casefold() == bot_username.lstrip("@").casefold()


def request(session: requests.Session, token: str, method: str,
            params: dict | None = None) -> object:
    """Never include Telegram token, private message, or chat ID in errors."""
    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=params or {}, timeout=18, allow_redirects=False,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Telegram {method} returned HTTP {response.status_code}")
        result = response.json()
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError(f"Telegram {method} returned an API error")
        return result.get("result")
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Telegram {method} failed (private details hidden)") from None


def handle_update(update: object, bot_name: str, token: str,
                  session: requests.Session, now: int) -> bool:
    """Return True if the user's voluntary command got a welcome reply."""
    if not isinstance(update, dict):
        return False
    message = update.get("message")
    if not command_requested(message, bot_name):
        return False
    sent_at = message.get("date")
    if not isinstance(sent_at, int) or not (now - MAX_AGE_SECONDS <= sent_at <= now + 120):
        # Never send a surprise welcome to someone who started ages ago.
        return False
    chat_id = message["chat"].get("id")
    if type(chat_id) is not int or chat_id <= 0:
        return False
    payload = {
        "chat_id": chat_id,
        "text": WELCOME_TEXT,
        "link_preview_options": {"is_disabled": True},
        "reply_markup": KEYBOARD,
        "disable_notification": False,
    }
    result = request(session, token, "sendMessage", payload)
    if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
        raise RuntimeError("Telegram did not confirm the private welcome reply")
    return True


def poll_bot(session: requests.Session, token: str, state: dict[str, int],
             checked_bot_ids: set[str], now: int | None = None) -> tuple[int, int]:
    """Read and respond to fresh opt-in starts for one distinct Telegram bot."""
    if not token:
        return 0, 0
    identity = request(session, token, "getMe")
    if not isinstance(identity, dict) or type(identity.get("id")) is not int:
        raise RuntimeError("Telegram returned an invalid bot identity")
    bot_id = str(identity["id"])
    if bot_id in checked_bot_ids:
        print("Duplicate configured bot token; no second polling.")
        return 0, 0
    checked_bot_ids.add(bot_id)

    webhook = request(session, token, "getWebhookInfo")
    if not isinstance(webhook, dict):
        raise RuntimeError("Cannot verify Telegram webhook status")
    if webhook.get("url"):
        print("Bot @" + str(identity.get("username", "unknown")) +
              " uses a webhook; skipping polling without changing its settings.")
        return 0, 0

    count, processed = 0, 0
    timestamp = int(time.time()) if now is None else now
    for _ in range(MAX_BATCHES):
        updates = request(session, token, "getUpdates", {
            "offset": state.get(bot_id, 0),
            "limit": MAX_UPDATES,
            "timeout": 0,
            "allowed_updates": ["message"],
        })
        if not isinstance(updates, list):
            raise RuntimeError("Telegram sent invalid updates")
        if not updates:
            break
        for item in updates:
            if not isinstance(item, dict) or type(item.get("update_id")) is not int:
                continue
            update_id = item["update_id"]
            if update_id < state.get(bot_id, 0):
                continue
            if handle_update(item, str(identity.get("username", "")),
                             token, session, timestamp):
                count += 1
            # Update ID advances ONLY after a successful reply or a skipped
            # irrelevant update, not after failed Telegram send.
            state[bot_id] = update_id + 1
            processed += 1
        if len(updates) < MAX_UPDATES:
            break
    print("Bot @" + str(identity.get("username", "unknown")) +
          ": replied to " + str(count) + " new private starts; updates checked " +
          str(processed) + ".")
    return count, processed


def main() -> int:
    tokens = (
        os.environ.get("AFISHA_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
    )
    if not any(tokens):
        print("No Serbia24 bot tokens configured; no welcome checks.")
        return 0
    state = read_state()
    seen_ids: set[str] = set()
    errors = 0
    session = requests.Session()
    for token in tokens:
        if not token:
            continue
        try:
            poll_bot(session, token, state, seen_ids)
        except RuntimeError as error:
            # Errors have no tokens, chat IDs, usernames of subscribers, or
            # message contents. Continue checking the other distinct bot.
            print(str(error), file=sys.stderr)
            errors += 1
        finally:
            # Write successful offsets even when a subsequent send fails;
            # persistence workflow will retry merging with other GitHub jobs.
            write_state(state)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
