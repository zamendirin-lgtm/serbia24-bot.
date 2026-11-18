"""Welcome users who open the Serbia24 news publishing bot in Telegram.

The news publisher sends channel posts separately. This small, scheduled
inbox handler only handles private /start, /help and /news commands.
It cannot subscribe a Telegram user on their behalf.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("serbia24.onboarding")

CHANNEL_URL = "https://t.me/serbia24live"
AFISHA_URL = "https://t.me/Serbia24Afisha"
MARKET_URL = "https://t.me/baraholka_serbia"
STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "news_bot_onboarding_state.json"
WELCOME_TEXT = (
    "🇷🇸 <b>Сербия 24 — наши каналы</b>\n\n"
    "📰 <b>Новости Сербии</b> — главное: важные события, цены, законы, "
    "экономика и происшествия.\n"
    "🎭 <b>Афиша</b> — концерты, выставки и интересные мероприятия.\n"
    "🛍 <b>Барахолка Сербии</b> — объявления и предложения.\n\n"
    "Выберите канал ниже и нажмите «Подписаться» в Telegram."
)
SHORT_DESCRIPTION = (
    "🇷🇸 Новости: @serbia24live | Афиша: @Serbia24Afisha | "
    "Барахолка: @baraholka_serbia"
)
DESCRIPTION = (
    "🇷🇸 Сербия 24 — новости, афиша и барахолка на русском языке.\n\n"
    "📰 Главное — новости Сербии: https://t.me/serbia24live\n"
    "🎭 Концерты и события: https://t.me/Serbia24Afisha\n"
    "🛍 Объявления и покупки: https://t.me/baraholka_serbia\n\n"
    "Нажмите «Запустить», чтобы выбрать канал и подписаться."
)

class TelegramAPIError(RuntimeError):
    """A Telegram call failed without exposing the bot token."""


def telegram_api(token: str, method: str, payload: dict) -> object:
    """Use stdlib only; never log token, private messages or request URLs."""
    request = Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        # Telegram's error body or the request URL may contain credentials.
        raise TelegramAPIError(
            "Telegram method " + method + " failed (" + type(exc).__name__ + ")"
        ) from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise TelegramAPIError("Telegram rejected " + method)
    return result.get("result")


def subscribe_keyboard() -> dict:
    """The main news channel appears first; other projects remain optional."""
    return {
        "inline_keyboard": [
            [{"text": "📰 Подписаться на новости", "url": CHANNEL_URL}],
            [{"text": "🎭 Афиша Сербии", "url": AFISHA_URL}],
            [{"text": "🛍 Барахолка Сербии", "url": MARKET_URL}],
        ]
    }


def should_welcome(update: dict) -> bool:
    """Never answer in groups or respond to random old private messages."""
    if not isinstance(update, dict):
        return False
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    chat = message.get("chat", {})
    author = message.get("from", {})
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return False
    if isinstance(author, dict) and author.get("is_bot") is True:
        return False
    text = message.get("text", "")
    if not isinstance(text, str):
        return False
    return bool(re.match(r"^/(?:start|help|news)(?:@[A-Za-z0-9_]+)?(?:\s|$)", text.strip(), re.I))


def default_state() -> dict:
    return {"next_offset": 0, "profile_configured": False}


def read_state(path: Path = STATE_FILE) -> dict:
    if not path.exists():
        return default_state()
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(saved, dict)
        or type(saved.get("next_offset")) is not int
        or saved["next_offset"] < 0
        or type(saved.get("profile_configured")) is not bool
    ):
        raise ValueError("Invalid Telegram onboarding offset state")
    return saved


def write_state(state: dict, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def configure_profile(token: str, api=telegram_api) -> None:
    """Make the channel discoverable even before a person presses Start."""
    api(token, "setMyShortDescription", {"short_description": SHORT_DESCRIPTION})
    api(token, "setMyDescription", {"description": DESCRIPTION})
    api(token, "setMyCommands", {
        "commands": [
            {"command": "start", "description": "Подписаться на новости Сербии"},
            {"command": "news", "description": "Перейти в новостной канал"},
            {"command": "help", "description": "Как подписаться"},
        ],
        "scope": {"type": "all_private_chats"},
    })


def process_updates(
    token: str,
    updates: object,
    state: dict,
    *,
    api=telegram_api,
    persist=write_state,
) -> int:
    """Persist each completed update; failed sends get retried next run."""
    if not isinstance(updates, list):
        raise TelegramAPIError("Unexpected Telegram updates format")
    replied = 0
    for update in updates:
        if not isinstance(update, dict) or type(update.get("update_id")) is not int:
            continue
        update_id = update["update_id"]
        if update_id < state["next_offset"]:
            continue
        if should_welcome(update):
            chat_id = update["message"]["chat"].get("id")
            if type(chat_id) is int:
                api(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": WELCOME_TEXT,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": subscribe_keyboard(),
                })
                replied += 1
        state["next_offset"] = update_id + 1
        persist(state)
    return replied


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        LOG.warning("TELEGRAM_BOT_TOKEN is not set; onboarding is inactive.")
        return
    state = read_state()
    if not state["profile_configured"]:
        try:
            configure_profile(token)
        except TelegramAPIError:
            LOG.warning("Could not configure bot profile; will retry next run.")
        else:
            state["profile_configured"] = True
            write_state(state)
    updates = telegram_api(token, "getUpdates", {
        "offset": state["next_offset"],
        "limit": 100,
        "timeout": 0,
        "allowed_updates": ["message"],
    })
    replied = process_updates(token, updates, state)
    LOG.info("Telegram updates processed: %d; welcome messages sent: %d",
             len(updates), replied)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
