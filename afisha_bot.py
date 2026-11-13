"""Serbia 24 | Afisha: independent, source-linked Serbia event announcements.

First source: Novi Sad Tourism Organisation's public events calendar. Only brief
factual metadata is used; original event media is represented by a link preview,
not copied. Curated, owner-authorized JSON is accepted for other Serbian cities.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Europe/Belgrade")
STATE = Path("data/afisha_seen.json")
BASE = "https://novisad.travel"
SOURCE = BASE + "/en/kalendar-dogadjaja/kategorija/calendar-of-events/list/"
UA = "Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
MAX_LINKS = 16
MAX_POSTS = 1
CITY_NAMES = {
    "novi sad": "Нови-Сад", "beograd": "Белград", "belgrade": "Белград",
    "nis": "Ниш", "niš": "Ниш", "pancevo": "Панчево",
    "pančevo": "Панчево", "subotica": "Суботица",
    "kragujevac": "Крагуевац", "zrenjanin": "Зренянин",
}
PRICE_RE = re.compile(
    r"(?:ulaznic[aeu]?|cena\s+karte|cena\s+ulaznice|ticket\s+price|admission\s+fee|entry\s+fee)"
    r".{0,45}?(?:od\s+|from\s+)?(\d[\d., ]{0,8})\s*(RSD|din(?:ara)?|€|EUR)",
    re.IGNORECASE,
)
FREE_RE = re.compile(
    r"(?:ulaz\s+(?:je\s+)?slobodan|besplatan\s+ulaz|besplatn[aoe]\s+ulaznic[aeu]?|"
    r"free\s+admission|free\s+entry|entrance\s+is\s+free)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Event:
    url: str
    title: str
    city: str
    venue: str
    start: datetime
    end: datetime | None = None
    description: str = ""
    category: str = ""
    price: str = "Стоимость уточняется"
    image: str = ""
    image_permission: bool = False

    @property
    def key(self) -> str:
        # Repeat occurrences of one event at different dates are independent.
        raw = self.url + "|" + self.start.isoformat()
        return hashlib.sha256(raw.encode("utf8")).hexdigest()


def safe_source_url(value: str, allowed_hosts: tuple[str, ...] = ("novisad.travel", "www.novisad.travel")) -> str:
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "", ""))


def clean(value: str, limit: int = 420) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)).strip()[:limit]


def parse_date(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.replace(tzinfo=TZ) if not d.tzinfo else d.astimezone(TZ)
    except ValueError:
        return None


def _iter_schema(value):
    if isinstance(value, list):
        for x in value:
            yield from _iter_schema(x)
    elif isinstance(value, dict):
        types = value.get("@type", "")
        if isinstance(types, str):
            types = [types]
        if any(t.lower().endswith("event") for t in types if isinstance(t, str)):
            yield value
        for k in ("@graph", "mainEntity", "itemListElement", "events"):
            if k in value:
                yield from _iter_schema(value[k])


def event_price(item: dict, body: str) -> str:
    free = item.get("isAccessibleForFree")
    if free is True or str(free).lower() == "true":
        return "Бесплатно (по данным организатора)"
    offers = item.get("offers", [])
    if not isinstance(offers, list):
        offers = [offers]
    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        price = offer.get("lowPrice", offer.get("price"))
        currency = str(offer.get("priceCurrency", "RSD")).upper()
        if currency not in ("RSD", "EUR"):
            continue
        try:
            number = float(str(price).replace(",", "."))
        except (ValueError, TypeError):
            continue
        if number >= 0:
            prices.append((number, currency))
    if prices:
        number, currency = min(prices)
        if number == 0:
            return "Бесплатно (по данным организатора)"
        suffix = "дин." if currency == "RSD" else "€"
        prefix = "от " if any(isinstance(o, dict) and "lowPrice" in o for o in offers) else ""
        return f"{prefix}{number:g} {suffix}"
    short = clean(body, 4000)
    if FREE_RE.search(short):
        return "Бесплатно (по данным источника)"
    match = PRICE_RE.search(short)
    if match:
        number = match.group(1).strip()
        units = "дин." if match.group(2).lower() not in ("€", "eur") else "€"
        return f"{number} {units} (по данным источника)"
    return "Стоимость уточняется"


def parse_jsonld_events(markup: str, url: str, city_fallback: str = "Нови-Сад") -> list[Event]:
    soup = BeautifulSoup(markup, "html.parser")
    collected: list[Event] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for item in _iter_schema(data):
            start = parse_date(item.get("startDate"))
            if not start:
                continue
            title = clean(item.get("name", ""), 110)
            if not title:
                continue
            location = item.get("location") or {}
            venue = ""
            city = city_fallback
            if isinstance(location, dict):
                venue = clean(location.get("name", ""), 90)
                addr = location.get("address") or {}
                if isinstance(addr, dict):
                    city_name = clean(addr.get("addressLocality", ""), 60)
                    city = CITY_NAMES.get(city_name.casefold(), city_fallback) if city_name else city_fallback
                elif isinstance(addr, str):
                    venue = venue or clean(addr, 90)
            elif isinstance(location, str):
                venue = clean(location, 90)
            source = item.get("url") or url
            if isinstance(source, list):
                source = source[0] if source else url
            source = safe_source_url(str(source))
            if not source:
                continue
            end = parse_date(item.get("endDate"))
            summary = clean(item.get("description", ""), 450)
            image = item.get("image") or ""
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url") or ""
            collected.append(Event(
                url=source, title=title, city=city, venue=venue, start=start,
                end=end, description=summary,
                category=clean(item.get("eventAttendanceMode", ""), 35),
                price=event_price(item, summary),
                image=image if isinstance(image, str) and image.startswith("https://") else "",
            ))
    return collected


def list_event_urls(markup: str, page: str = SOURCE) -> list[str]:
    """Only follow event-title links on the official calendar, never whole-site links."""
    soup = BeautifulSoup(markup, "html.parser")
    links, seen = [], set()
    selectors = (
        "h3.tribe-events-calendar-list__event-title a[href], "
        "h2.tribe-events-calendar-list__event-title a[href], "
        ".tribe-events-calendar-list__event-title-link[href], "
        ".type-tribe_events h3 a[href], "
        ".type-tribe_events h2 a[href]"
    )
    for anchor in soup.select(selectors):
        raw = urljoin(page, anchor.get("href", ""))
        url = safe_source_url(raw)
        if not url or url in seen or url == SOURCE.rstrip("/"):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= MAX_LINKS:
            break
    return links


def get_robots(session: requests.Session) -> RobotFileParser | None:
    try:
        result = session.get(BASE + "/robots.txt", timeout=12)
        result.raise_for_status()
    except requests.RequestException:
        print("Official event source robots.txt could not be checked; skipping source.")
        return None
    robot = RobotFileParser()
    robot.parse(result.text.splitlines())
    return robot


def collect_official_events(session: requests.Session, now: datetime) -> list[Event]:
    if os.getenv("AFISHA_ENABLE_TONS", "1") != "1":
        return []
    robots = get_robots(session)
    if not robots or not robots.can_fetch(UA, SOURCE):
        print("Official source does not allow this path or robots info unavailable.")
        return []
    try:
        result = session.get(SOURCE, timeout=18)
        result.raise_for_status()
    except requests.RequestException:
        print("Unable to read official events calendar.")
        return []
    urls = list_event_urls(result.text)
    print(f"Official event links discovered: {len(urls)}")
    found = []
    for url in urls:
        if not robots.can_fetch(UA, url):
            continue
        try:
            page = session.get(url, timeout=14)
            page.raise_for_status()
        except requests.RequestException:
            continue
        items = parse_jsonld_events(page.text, url)
        # Conservative: the detail page must contain a valid Event with its date.
        for item in items:
            if item.url == url and event_in_window(item, now):
                found.append(item)
        time.sleep(0.25)
    return found


def event_in_window(event: Event, now: datetime) -> bool:
    local_today = now.date()
    if event.end and event.end < event.start:
        return False
    if event.end:
        if event.end.date() < local_today:
            return False
    elif event.start.date() < local_today:
        return False
    return event.start.date() <= local_today + timedelta(days=30)


def load_curated_events(now: datetime) -> list[Event]:
    """Moderator-controlled factual event records for all Serbian cities."""
    path = Path("data/afisha_events.json")
    try:
        rows = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("approved") is not True:
            continue
        try:
            url = str(row["url"])
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            start = parse_date(row["start"])
            end = parse_date(row.get("end"))
            if not start:
                continue
            event = Event(
                url=url, title=clean(row["title"], 110),
                city=clean(row["city"], 70),
                venue=clean(row.get("venue", ""), 95),
                start=start, end=end,
                description=clean(row.get("description", ""), 430),
                category=clean(row.get("category", ""), 50),
                price=clean(row.get("price", ""), 75) or "Стоимость уточняется",
                image=str(row.get("image", "")),
                image_permission=row.get("image_permission") is True,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if event.title and event.city and event_in_window(event, now):
            found.append(event)
    return found


def translate_to_russian(value: str) -> str:
    value = clean(value, 430)
    if not value:
        return ""
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/t",
            params={"client": "dict-chrome-ex", "sl": "auto", "tl": "ru", "q": value},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        translated = data[0] if isinstance(data, list) and data else ""
        if isinstance(translated, str) and translated.strip():
            return clean(translated, 500)
    except (requests.RequestException, ValueError, IndexError, KeyError):
        pass
    return ""


def format_event(event: Event, title_ru: str = "", description_ru: str = "") -> str:
    title = html.escape(title_ru or event.title)
    description = html.escape(description_ru) if description_ru else (
        "Подробная программа и условия — на странице организатора."
    )
    if event.end and event.end.date() != event.start.date():
        when = f"{event.start:%d.%m.%Y}–{event.end:%d.%m.%Y}"
    else:
        when = event.start.strftime("%d.%m.%Y")
        if event.start.hour or event.start.minute:
            when += event.start.strftime(" в %H:%M")
    venue = " · " + html.escape(event.venue) if event.venue else ""
    link = html.escape(event.url, quote=True)
    return (
        f"🎭 <b>{title}</b>\n\n"
        f"📅 <b>Дата:</b> {when}\n"
        f"📍 <b>Город:</b> {html.escape(event.city)}{venue}\n"
        f"🎟 <b>Стоимость:</b> {html.escape(event.price)}\n\n"
        f"📝 {description[:500]}\n\n"
        f'🔗 <a href="{link}">Подробности и билеты — первоисточник</a>\n'
        f"ℹ️ Время и цену проверьте перед посещением."
    )


def load_seen() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def select(events: list[Event], seen: dict, now: datetime) -> list[Event]:
    unique = {e.key: e for e in events if e.key not in seen and event_in_window(e, now)}
    def score(e: Event):
        # Near-term events first, but allow ongoing exhibitions.
        delta = (e.start.date() - now.date()).days
        upcoming = max(delta, 0)
        ongoing_penalty = 7 if delta < 0 else 0
        cost_bonus = -1 if e.price.startswith("Бесплатно") else 0
        return (upcoming + ongoing_penalty + cost_bonus, e.start, e.title)
    return sorted(unique.values(), key=score)[:MAX_POSTS]


def publish(session: requests.Session, token: str, chat: str, post: str, source_url: str) -> bool:
    """Link preview may show the organizer photo; no image is downloaded/rehosted."""
    try:
        result = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat, "parse_mode": "HTML", "text": post,
                "link_preview_options": {
                    "is_disabled": False,
                    "url": source_url,
                    "prefer_large_media": True,
                    "show_above_text": True,
                },
            },
            timeout=22,
        )
        if result.ok:
            return result.json().get("ok") is True
        print(f"Telegram status {result.status_code}; check AFISHA_CHAT_ID and bot rights.")
    except (requests.RequestException, ValueError):
        print("Telegram send failed.")
    return False


def main() -> int:
    now = datetime.now(TZ)
    if not (8 <= now.hour < 22) and os.getenv("AFISHA_ALLOW_NIGHT", "") != "1":
        print("Quiet hours for Serbia 24 Afisha.")
        return 0
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    chat = os.getenv("AFISHA_CHAT_ID", "").strip()
    dry = os.getenv("AFISHA_DRY_RUN") == "1"
    if not dry and not (token and chat):
        print("AFISHA_BOT_TOKEN or AFISHA_CHAT_ID not set; no publication.")
        return 0
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    events = load_curated_events(now) + collect_official_events(session, now)
    seen = load_seen()
    shortlisted = select(events, seen, now)
    print(f"Eligible upcoming event candidates: {len(events)}, selected: {len(shortlisted)}")
    for event in shortlisted:
        title = translate_to_russian(event.title)
        summary = translate_to_russian(event.description) if event.description else ""
        post = format_event(event, title, summary)
        if dry:
            print(post)
            continue
        if publish(session, token, chat, post, event.url):
            seen[event.key] = {
                "url": event.url, "event_start": event.start.isoformat(),
                "published_at": now.isoformat(),
            }
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
            print("Afisha announcement sent.")
        else:
            return 1
    if not shortlisted:
        print("No verified upcoming event to publish; skipping rather than inventing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
