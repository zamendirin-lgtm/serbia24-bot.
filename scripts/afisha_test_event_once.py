"""One user-authorized Afisha test post with a real, verified, pictured event.

Uses the official Novi Sad Tourism Organisation page, no fabricated details,
one-time history protection, Telegram photo verification and quiet-hours rules.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from afisha_bot import Event, STATE, TZ, UA, load_seen, posted_today, post_spacing_ok, publication_allowed

SOURCE = "https://novisad.travel/en/kalendar-dogadjaja/international-tourism-fair/"
PHOTO = "https://novisad.travel/wp-content/uploads/2019/05/Medunarodni-sajam-turizma_1.jpg"
CHANNEL = "@Serbia24Afisha"
EXPECTED_START = "2026-11-26"
EXPECTED_END = "2026-11-28"
TEST_KEY = hashlib.sha256(("one-time-verified-afisha-photo-test-2026-11-15|" + SOURCE).encode()).hexdigest()

CAPTION = (
    "🧳 <b>Международная туристическая ярмарка в Нови-Саде</b>\n\n"
    "📅 <b>Дата:</b> 26–28 ноября 2026 года\n"
    "📍 <b>Город:</b> Нови-Сад\n"
    "🏛 <b>Место:</b> Новосадская ярмарка (Novosadski sajam)\n"
    "🎟 <b>Вход:</b> бесплатный\n\n"
    "📝 Туристические организации, агентства и отели представят направления "
    "для путешествий, предложения для зимнего и летнего отдыха, а также "
    "возможности спа- и городского туризма. В программе — профессиональные "
    "встречи и презентации туристической отрасли.\n\n"
    f'🔗 <a href="{html.escape(SOURCE, quote=True)}">Источник</a>\n'
    f'📷 <a href="{html.escape(PHOTO, quote=True)}"> </a>'
)
# The icon itself must be clickable; do not put it outside the link.
CAPTION = CAPTION.replace(
    f'📷 <a href="{html.escape(PHOTO, quote=True)}"> </a>',
    f'<a href="{html.escape(PHOTO, quote=True)}">📷</a>',
)


def verified_source(session: requests.Session) -> bool:
    """Read the live official description and reject a stale or changed event."""
    try:
        robots = session.get("https://novisad.travel/robots.txt", timeout=12)
        robots.raise_for_status()
        robot = RobotFileParser()
        robot.parse(robots.text.splitlines())
        if not robot.can_fetch(UA, SOURCE):
            print("Official organiser disallows automated reading. Skipping.")
            return False
        response = session.get(SOURCE, timeout=20)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            return False
        soup = BeautifulSoup(response.text, "html.parser")
        title_node = soup.select_one("h1")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        if "International Tourism Fair" not in title:
            print("Unexpected event title; no test post.")
            return False
        text = soup.get_text(" ", strip=True).casefold()
        # The page gives these exact dates and explicitly says free entry.
        if (
            "novi sad fair" not in text
            or "free entry" not in text
            or EXPECTED_START not in response.text
            or EXPECTED_END not in response.text
        ):
            print("Event dates, venue, or free admission could not be confirmed.")
            return False
        if PHOTO not in html.unescape(response.text):
            print("Chosen event image not confirmed on the official page.")
            return False
        return True
    except (requests.RequestException, ValueError, TypeError):
        print("Unable to verify event with official source.")
        return False


def main() -> int:
    now = datetime.now(TZ)
    seen = load_seen()
    if TEST_KEY in seen or any(
        isinstance(row, dict) and row.get("url", "").rstrip("/") == SOURCE.rstrip("/")
        for row in seen.values()
    ):
        print("Tourism fair Afisha announcement is already in history; no duplicate.")
        return 0
    if not publication_allowed(now) or len(posted_today(seen, now)) >= 5 or not post_spacing_ok(seen, now):
        print("Afisha quiet hours, daily cap, or post-spacing rule; no test post.")
        return 0
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    if not token:
        print("Missing Afisha token; no publication.")
        return 1
    if len(CAPTION) > 1024:
        raise ValueError("Telegram photo caption is too long.")

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    if not verified_source(session):
        return 1

    try:
        image = session.get(PHOTO, timeout=20)
        image.raise_for_status()
        data = image.content
        if len(data) < 15000 or len(data) > 8_000_000 or not data.startswith(b"\xff\xd8\xff"):
            print("Unexpected official event photo; refusing text-only substitution.")
            return 1
        reply = session.post(
            "https://api.telegram.org/bot" + token + "/sendPhoto",
            data={"chat_id": CHANNEL, "caption": CAPTION, "parse_mode": "HTML"},
            files={"photo": ("tourism-fair.jpg", data, "image/jpeg")},
            timeout=35,
        )
        if not reply.ok:
            print("Telegram photo was not accepted. HTTP status: " + str(reply.status_code))
            return 1
        body = reply.json()
    except (requests.RequestException, ValueError):
        print("Photo could not be delivered to Telegram.")
        return 1
    result = body.get("result", {}) if isinstance(body, dict) else {}
    if body.get("ok") is not True or not result.get("photo"):
        print("Telegram did not confirm photo publication.")
        return 1
    message_id = result.get("message_id")
    seen[TEST_KEY] = {
        "url": SOURCE,
        "event_start": "2026-11-26T00:00:00+01:00",
        "published_at": datetime.now(TZ).isoformat(),
        "topic": "fair",
        "title": "International Tourism Fair",
        "city": "Нови-Сад",
        "venue": "Novi Sad Fair",
        "test_publish": True,
        "message_id": message_id,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print("Test Afisha event posted with a verified official event image and a linked camera-only icon.")
    if isinstance(message_id, int):
        print("CONFIRMED TELEGRAM POST: https://t.me/Serbia24Afisha/" + str(message_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
