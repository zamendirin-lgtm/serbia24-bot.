"""ONE-TIME user-authorized correction of the first Afisha Telegram post.

This is deliberately not a recurring or arbitrary nighttime posting endpoint.
No post outside early morning 13 Nov 2026. No post without the original event
in publication history. Exactly one correction. The official event promotional
poster is sent as a photo with a clean Russian-language caption, no link preview.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path

import requests

from afisha_bot import Event, STATE, TZ, _official_poster, format_event, load_seen


EVENT_URL = "https://novisad.travel/en/kalendar-dogadjaja/to-be-punk-festival"
POSTER = "https://novisad.travel/wp-content/uploads/2019/05/To-Be-Punk-festival-2026_1.jpeg"
CORRECTION_KEY = hashlib.sha256((EVENT_URL + "|corrected-photo-test|2026-11-13").encode()).hexdigest()
TARGET_CHAT = "@Serbia24Afisha"

TITLE = "Фестиваль To Be Punk в Нови-Саде"
DESCRIPTION = (
    "To Be Punk соберёт панк- и хардкор-группы из Сербии и других европейских стран. "
    "Гостей ждут живые выступления и атмосфера независимой музыкальной сцены."
)


def main() -> int:
    now = datetime.now(TZ)
    if now.date() != date(2026, 11, 13) or now.hour >= 8:
        print("This explicitly authorized correction is available only before 08:00 Serbia time on 13 Nov 2026.")
        return 0
    seen = load_seen()
    if CORRECTION_KEY in seen:
        print("Corrected Afisha test already published; no duplicate.")
        return 0
    if not any(isinstance(row, dict) and row.get("url") == EVENT_URL for row in seen.values()):
        print("Original Afisha event was not found in history; no correction posted.")
        return 1
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    if not token:
        print("Telegram bot token missing.")
        return 1
    if not _official_poster(POSTER):
        print("Refusing unverified photo host.")
        return 1

    event = Event(
        url=EVENT_URL,
        title="To Be Punk festival",
        city="Нови-Сад",
        venue="SKCNS Fabrika",
        start=datetime(2026, 11, 13, 0, 0, tzinfo=TZ),
        end=datetime(2026, 11, 14, 23, 59, tzinfo=TZ),
        description="Punk and hardcore groups from Serbia and Europe; live concerts.",
        price="не указана",
        image=POSTER,
    )
    caption = format_event(event, TITLE, DESCRIPTION)
    if "ℹ️" in caption or "проверьте перед посещением" in caption:
        raise RuntimeError("Old warning unexpectedly remains in caption.")
    if len(caption) > 1024:
        raise RuntimeError("Photo caption exceeds Telegram maximum.")
    try:
        result = requests.post(
            "https://api.telegram.org/bot" + token + "/sendPhoto",
            json={
                "chat_id": TARGET_CHAT,
                "photo": POSTER,
                "caption": caption,
                "parse_mode": "HTML",
                "show_caption_above_media": False,
            },
            timeout=30,
        )
        if not result.ok:
            print("Telegram did not accept the promotional poster: HTTP " + str(result.status_code))
            return 1
        body = result.json()
        if body.get("ok") is not True or not body.get("result", {}).get("photo"):
            print("Telegram did not confirm posting a photo; correction unconfirmed.")
            return 1
    except (requests.RequestException, ValueError):
        print("Corrected Telegram photo send failed; credentials are not logged.")
        return 1

    message_id = body["result"].get("message_id")
    seen[CORRECTION_KEY] = {
        "url": EVENT_URL,
        "published_at": now.isoformat(),
        "event_start": event.start.isoformat(),
        "topic": "festival",
        "corrected_test": True,
        "message_id": message_id,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf8")
    print("Corrected Afisha photo posted with clean Russian caption.")
    if isinstance(message_id, int):
        print("Telegram confirmed message id: " + str(message_id))
        print("Public link: https://t.me/Serbia24Afisha/" + str(message_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
