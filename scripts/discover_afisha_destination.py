"""Read-only discovery of the repurposed Serbian Afisha Telegram channel.

Uses the existing bot's credentials through GitHub Actions secrets and only
accepts a Telegram chat with an Afisha title and explicit post permission.
Never posts messages, confirms (consumes) updates or logs bot tokens.
"""
from __future__ import annotations

import os
import sys
import requests

ALIASES = ("@Serbia24Dom", "@Serbia24Nedvizhimost", "@Serbia24Afisha")


def telegram(token: str, method: str, params: dict) -> object | None:
    try:
        response = requests.post(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=params, timeout=15, allow_redirects=False,
        )
        if response.status_code != 200:
            # Common cases: no access to a guessed channel, or a bot webhook in use.
            return None
        data = response.json()
        return data.get("result") if data.get("ok") else None
    except (requests.RequestException, ValueError):
        return None


def verify(token: str, bot_id: int, chat_ref) -> dict | None:
    chat = telegram(token, "getChat", {"chat_id": chat_ref})
    if not isinstance(chat, dict) or chat.get("type") not in ("channel", "supergroup"):
        return None
    title = chat.get("title", "")
    if not isinstance(title, str) or "афиш" not in title.casefold():
        return None
    member = telegram(token, "getChatMember", {"chat_id": chat["id"], "user_id": bot_id})
    if not isinstance(member, dict):
        return None
    if chat["type"] == "channel":
        if member.get("status") not in ("administrator", "creator"):
            return None
        if member.get("status") == "administrator" and member.get("can_post_messages") is not True:
            return None
    elif member.get("status") in ("kicked", "left", "restricted"):
        return None
    return {
        "id": chat["id"],
        "title": title,
        "username": chat.get("username"),
        "type": chat["type"],
    }


def discover(token: str) -> dict | None:
    bot = telegram(token, "getMe", {})
    if not isinstance(bot, dict) or not isinstance(bot.get("id"), int):
        print("Bot token is unavailable or cannot authorize with Telegram.")
        return None
    candidates = list(ALIASES)
    updates = telegram(token, "getUpdates", {"limit": 100, "timeout": 0})
    if isinstance(updates, list):
        for entry in reversed(updates):
            if not isinstance(entry, dict):
                continue
            for field in ("my_chat_member", "channel_post", "edited_channel_post", "message"):
                update = entry.get(field)
                if not isinstance(update, dict):
                    continue
                chat = update.get("chat")
                if not isinstance(chat, dict):
                    continue
                title = chat.get("title", "")
                if isinstance(title, str) and "афиш" in title.casefold():
                    candidates.append(chat.get("id"))
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, (str, int)) or candidate in seen:
            continue
        seen.add(candidate)
        validated = verify(token, bot["id"], candidate)
        if validated:
            return validated
    return None


def main() -> int:
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    if not token:
        print("No available Afisha bot token.")
        return 0
    chat = discover(token)
    if not chat:
        print("NO_AFISHA_CHAT_FOUND: Add AFISHA_CHAT_ID under GitHub Actions Variables.")
        print("Bot discovery is limited to public aliases and recent Telegram updates.")
        return 0
    print("AFISHA_CHANNEL_CONFIRMED")
    print("Verified channel: %s" % chat["title"][:120])
    print("Verified chat ID: %s" % chat["id"])
    if chat.get("username"):
        print("Verified username: @%s" % chat["username"])
    print("This was a read-only test; no posts were sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
