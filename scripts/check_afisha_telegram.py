"""Verify reused Telegram credentials point to an Afisha channel before publishing.

Never print tokens or HTTP exception strings (requests may contain credential URLs).
"""
from __future__ import annotations

import os
import sys

import requests


def _request(token: str, method: str, data: dict) -> dict:
    try:
        result = requests.post(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=data, timeout=15, allow_redirects=False,
        )
        if result.status_code != 200:
            raise RuntimeError(f"Telegram {method}: HTTP {result.status_code}")
        body = result.json()
        if body.get("ok") is not True or not isinstance(body.get("result"), dict):
            raise RuntimeError(f"Telegram {method}: authorization or chat access failed")
        return body["result"]
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Telegram {method}: network/API error (credentials hidden)") from None


def main() -> int:
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    chat = os.getenv("AFISHA_CHAT_ID", "").strip()
    if not token or not chat:
        print("Missing Afisha bot token or destination; no posts.")
        return 1

    try:
        bot = _request(token, "getMe", {})
        target = _request(token, "getChat", {"chat_id": chat})
        title = target.get("title", "")
        chat_type = target.get("type", "")
        if not isinstance(title, str) or "афиш" not in title.casefold():
            print("Destination title is not an Afisha channel/group; publishing blocked.")
            return 1
        if chat_type not in ("channel", "supergroup", "group"):
            print("Destination is not a Telegram channel/group; publishing blocked.")
            return 1
        member = _request(
            token, "getChatMember", {"chat_id": target["id"], "user_id": bot["id"]}
        )
        if chat_type == "channel" and (
            member.get("status") not in ("administrator", "creator")
            or (member.get("status") == "administrator" and member.get("can_post_messages") is False)
        ):
            print("Bot is not allowed to post to Afisha channel; grant admin/post rights.")
            return 1
        if chat_type != "channel" and member.get("status") in ("left", "kicked", "restricted"):
            print("Bot cannot post to the Afisha group.")
            return 1
        print(
            "Telegram access confirmed. Bot @%s, destination: %s, type: %s."
            % (bot.get("username", "unknown"), title[:110], chat_type)
        )
        return 0
    except (RuntimeError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
