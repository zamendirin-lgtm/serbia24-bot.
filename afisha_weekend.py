"""Small, source-linked Friday weekend roundup as ONE of the six daily posts."""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime
from urllib.parse import urlparse

from afisha_bot import (
    STATE, TZ, branded_poster, edit_event, event_topic,
    finalize_afisha_post, monthly_reminder_due, posting_slot, publish,
)


def weekend_candidates(shortlist, seen: dict, now: datetime):
    """Choose three unused Saturday/Sunday events, not three variants of a concert."""
    if now.astimezone(TZ).weekday() != 4 or posting_slot(now) != 2:
        return []
    weekend = []
    used_topics = set()
    used_series = set()
    for event in shortlist:
        delta = (event.start.astimezone(TZ).date() - now.astimezone(TZ).date()).days
        if delta not in (1, 2) or monthly_reminder_due(event, seen, now):
            continue
        topic = event_topic(event)
        series = (topic, event.venue.casefold())
        if topic in used_topics or series in used_series:
            continue
        used_topics.add(topic)
        used_series.add(series)
        weekend.append(event)
        if len(weekend) == 3:
            break
    return weekend if len(weekend) == 3 else []


def format_weekend(entries) -> str:
    """Only AI-vetted titles + facts already checked against event sources."""
    parts = ["🎉 <b>Куда сходить в выходные: 3 идеи</b>"]
    for event, edited in entries:
        day = "Сб" if event.start.astimezone(TZ).weekday() == 5 else "Вс"
        moment = event.start.astimezone(TZ).strftime("%d.%m")
        if event.start.hour or event.start.minute:
            moment += event.start.astimezone(TZ).strftime(" в %H:%M")
        title = html.escape(edited.title_ru[:83])
        city = html.escape(event.city)
        venue = html.escape(event.venue[:44])
        price = html.escape(event.price[:46])
        url = html.escape(event.url, quote=True)
        parts.append(
            f"<b>{title}</b>\n"
            f"📅 {day}, {moment} · {city}\n"
            + (f"🏛 {venue}\n" if venue else "")
            + f"🎟 {price} · <a href=\"{url}\">Подробнее</a>"
        )
    return finalize_afisha_post("\n\n".join(parts))


def create_weekend_history(seen, entries, now):
    """One actual Telegram message; individual events tagged to prevent reposts."""
    stamp = now.isoformat()
    digest_key = hashlib.sha256(("weekend|" + stamp).encode()).hexdigest()
    seen[digest_key] = {
        "url": "https://t.me/Serbia24Afisha",
        "published_at": stamp, "topic": "weekend",
        "city": "Сербия", "venue": "", "title": "Афиша выходных",
    }
    for event, edited in entries:
        # A bundled item has a timestamp for reminders/dedupe but does not
        # count as a separate Telegram message in daily-limit calculations.
        seen[event.key] = {
            "url": event.url, "event_start": event.start.isoformat(),
            "published_at": stamp, "digest_item": True,
            "topic": event_topic(event),
            "title": event.title, "city": event.city, "venue": event.venue,
            "included_in_roundup": stamp, "ai_editor": edited.provider,
        }


def maybe_publish_weekend(session, token, chat, shortlist, seen, now, *, dry=False) -> bool:
    selected = weekend_candidates(shortlist, seen, now)
    if len(selected) != 3:
        return False
    checked = []
    for event in selected:
        edited = edit_event(event)
        if edited is None:
            return False
        checked.append((event, edited))
    post = format_weekend(checked)
    if len(post) > 1024:
        print("Afisha Friday roundup too long; using regular event instead.")
        return False
    if dry:
        print("Afisha Friday roundup preview (no Telegram):\n" + post)
        return True
    card = branded_poster("Афиша выходных: 3 идеи", "Сербия", now.strftime("%d.%m.%Y"))
    if not publish(session, token, chat, post, checked[0][0].url, generated_card=card):
        return False
    create_weekend_history(seen, checked, now)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print("Afisha Friday roundup published as one verified message.")
    return True
