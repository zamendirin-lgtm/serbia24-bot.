#!/usr/bin/env python3
"""Fail closed if the selected Telegram bot cannot post to the target channel."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

token = os.getenv("REALITY_BOT_TOKEN", "").strip()
chat = os.getenv("REALITY_CHAT_ID", "@priroda_realnosti")
dry = os.getenv("REALITY_DRY_RUN", "false").lower() in ("1", "true")
if not token:
    if dry:
        print("REALITY_VERIFY: dry-run without credentials; no Telegram connection tested")
        sys.exit(0)
    print("REALITY_VERIFY_ERROR: REALITY_BOT_TOKEN is missing from GitHub Actions Secrets")
    sys.exit(1)


def api(method, args=None):
    url = "https://api.telegram.org/bot" + token + "/" + method
    if args:
        url += "?" + urlencode(args)
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        print("REALITY_VERIFY_ERROR: Telegram endpoint failed for", method)
        sys.exit(1)
    if not payload.get("ok"):
        print("REALITY_VERIFY_ERROR: Telegram refused", method)
        sys.exit(1)
    return payload["result"]


bot = api("getMe")
info = api("getChat", {"chat_id": chat})
if info.get("type") != "channel":
    print("REALITY_VERIFY_ERROR: destination is not a Telegram channel")
    sys.exit(1)
user = api("getChatMember", {"chat_id": chat, "user_id": bot["id"]})
if user.get("status") not in ("administrator", "creator") or not user.get("can_post_messages", False):
    print("REALITY_VERIFY_ERROR: bot is not an administrator with post permissions")
    sys.exit(1)
print("REALITY_CONNECTION_OK bot=@" + bot.get("username", "") +
      " channel=@" + info.get("username", "") + " can_post=true")
