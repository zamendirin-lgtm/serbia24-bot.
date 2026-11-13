"""One-time corrected Afisha post: exhibition admission with a licensed photo.

The original RUN BGD listing showed the cheapest category (300 RSD), not
the full adult price (600 RSD). The museum's own visitor tariff and exhibition
page are the primary sources. This post is user-authorized and idempotent.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import requests

from afisha_bot import STATE, TZ, load_seen, publication_allowed

TARGET_CHAT = "@Serbia24Afisha"
ORIGINAL_PREFIX = "https://www.runbgd.com/whats-on/prekretnice-ka-modernosti"
SOURCE = "https://msub.org.rs/exhibition/prekretnice-ka-modernosti-umetnost-drustva-1900-1945/"
TICKETS = (
    "https://tickets.rs/event/"
    "prekretnice_ka_modernosti_umetnost_drustva_19001945_"
    "predrag_neskovic_zemlja_vazduh_zarko_baseski_korporealnost_29084"
)
PHOTO_SOURCE = (
    "https://commons.wikimedia.org/wiki/"
    "File:20241019_151947911_Muzej_savremene_umjetnosti_Beograd.jpg"
)
PHOTO_URL = (
    "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/"
    "20241019_151947911_Muzej_savremene_umjetnosti_Beograd.jpg/"
    "960px-20241019_151947911_Muzej_savremene_umjetnosti_Beograd.jpg"
    "?utm_campaign=index&utm_content=thumbnail&utm_source=commons.wikimedia.org"
)
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
REPOST_KEY = hashlib.sha256(
    b"afisha-museum-repost-accurate-admission-photo-2026-11-13"
).hexdigest()

CAPTION = (
    "🇷🇸 <b>Сербия 24 | Афиша</b>\n\n"
    "🎨 <b>«Повороты к модернизму»: искусство 1900–1945</b>\n\n"
    "📍 <b>Город:</b> Белград\n"
    "🏛 <b>Место:</b> Музей современного искусства, Ушче, 10\n"
    "📅 <b>Выставка открыта:</b> до 1 марта 2027 года\n"
    "🎟 <b>Билеты:</b> обычный — 600 дин., льготный — 300 дин.\n\n"
    "🖼 Более 400 произведений 150 авторов рассказывают о развитии "
    "искусства Сербии и Югославии первой половины XX века.\n\n"
    f'🔗 <a href="{SOURCE}">Источник: музей</a>\n'
    f'🎟 <a href="{TICKETS}">Купить билеты</a>\n'
    f'📷 Фото здания: <a href="{PHOTO_SOURCE}">Niegodzisie</a>'
    f' (<a href="{LICENSE_URL}">CC BY 4.0</a>)'
)


def check_photo(data: bytes) -> bool:
    """Only actual, reasonably sized JPEG bytes can be sent as a photo."""
    return len(data) > 10000 and len(data) < 9_000_000 and data.startswith(b"\xff\xd8\xff")


def main() -> int:
    seen = load_seen()
    if REPOST_KEY in seen:
        print("Accurate museum post already published. Skipping duplicate.")
        return 0
    if not any(
        isinstance(item, dict) and str(item.get("url", "")).startswith(ORIGINAL_PREFIX)
        for item in seen.values()
    ):
        print("Original museum Afisha post missing in history; no new post sent.")
        return 1

    now = datetime.now(TZ)
    if not publication_allowed(now, seen=seen):
        print("Museum correction blocked outside Serbian Afisha posting hours.")
        return 1

    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    if not token:
        print("Afisha Telegram credentials missing.")
        return 1
    if len(CAPTION) > 1024:
        raise ValueError("Caption longer than Telegram's photo-caption limit.")
    try:
        photo = requests.get(
            PHOTO_URL,
            headers={"User-Agent": "Serbia24Afisha/1.0 contact: @Serbia24Afisha"},
            timeout=25,
        )
        photo.raise_for_status()
        if not check_photo(photo.content):
            print("Photo is not a valid JPEG; no text-only post will be sent.")
            return 1
        reply = requests.post(
            "https://api.telegram.org/bot" + token + "/sendPhoto",
            data={"chat_id": TARGET_CHAT, "caption": CAPTION, "parse_mode": "HTML"},
            files={"photo": ("muzej-savremene-umetnosti.jpg", photo.content, "image/jpeg")},
            timeout=40,
        )
        if not reply.ok:
            print("Telegram rejected museum photo: HTTP " + str(reply.status_code))
            return 1
        body = reply.json()
    except (requests.RequestException, ValueError):
        print("Photo download or Telegram photo publication failed.")
        return 1

    info = body.get("result", {}) if isinstance(body, dict) else {}
    if body.get("ok") is not True or not info.get("photo"):
        print("Telegram did not confirm a photo in the message; no history recorded.")
        return 1

    message_id = info.get("message_id")
    seen[REPOST_KEY] = {
        "url": SOURCE,
        "published_at": now.isoformat(),
        "event_start": now.isoformat(),
        "topic": "exhibition",
        "corrected_test": True,
        "message_id": message_id,
        "replaces": ORIGINAL_PREFIX,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print("Museum correction with Wikimedia Commons CC BY photo successfully posted.")
    if isinstance(message_id, int):
        print(f"Telegram confirmed message: https://t.me/Serbia24Afisha/{message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
