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
from afisha_editor import edit_event

TZ = ZoneInfo("Europe/Belgrade")
STATE = Path("data/afisha_seen.json")
BASE = "https://novisad.travel"
SOURCE = BASE + "/en/kalendar-dogadjaja/kategorija/calendar-of-events/list/"
UA = "Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
MAX_LINKS = 32
MAX_POSTS = 1  # only one good event per run
PRICE_UNKNOWN = "не указана"
MAX_DAILY_POSTS = 5
SELECTION_POOL = 12
MIN_INTEREST_SCORE = 52
FIRST_POST_ONLY_DATE = date(2026, 11, 13)
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
    price: str = PRICE_UNKNOWN
    image: str = ""
    image_permission: bool = False
    ticket_url: str = ""

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


def safe_ticket_url(url: str, source_url: str) -> str:
    """Only a distinct HTTPS event checkout/booking page can be a ticket link."""
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url)
        origin = urlparse(source_url)
    except ValueError:
        return ""
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password
        or parsed.hostname in ("localhost", "127.0.0.1")
    ):
        return ""
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))
    src_normalized = urlunparse((origin.scheme, origin.netloc, origin.path or "/", "", origin.query, ""))
    if normalized.rstrip("/") == src_normalized.rstrip("/"):
        return ""
    # Links to a seller's landing page are not event-specific booking pages.
    if parsed.path in ("", "/") and not parsed.query:
        return ""
    return normalized


def find_ticket_link(soup: BeautifulSoup, structured: dict, source_url: str) -> str:
    """Use explicitly labeled real purchase/registration links, never generic details.

    A generic "Tickets" label on the source page without a distinct URL does
    not authorize a second link.
    """
    area = soup.select_one(".tribe-events-single") or soup
    ticket_labels = re.compile(
        r"(?:\b(?:buy\s+tickets?|book\s+now|purchase\s+tickets?|tickets?|"
        r"kupi(?:te)?\s+(?:kartu|karte|ulaznice)|kupovina\s+(?:karata|ulaznica)|"
        r"rezervi(?:ši|site|s[iš]|sati)|ulaznice|karte)\b)",
        re.IGNORECASE,
    )
    for a in area.select("a[href]"):
        label = clean(a.get_text(" ", strip=True), 100)
        if not ticket_labels.search(label):
            continue
        candidate = safe_ticket_url(urljoin(source_url, a.get("href", "")), source_url)
        if candidate:
            return candidate
    offers = structured.get("offers") or []
    if not isinstance(offers, list):
        offers = [offers]
    for offer in offers:
        if isinstance(offer, dict) and isinstance(offer.get("url"), str):
            candidate = safe_ticket_url(offer["url"], source_url)
            if candidate:
                return candidate
    return ""


def clean(value: str, limit: int = 420) -> str:
    raw = str(value or "")
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()[:limit]


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
    return PRICE_UNKNOWN


def visible_event_dates(soup: BeautifulSoup) -> tuple[date | None, date | None]:
    """Prefer visitor-facing ISO dates near Start/End labels if JSON-LD differs."""
    content = soup.select_one(".tribe-events-single") or soup
    displayed = content.get_text(" ", strip=True)

    def dated_label(label: str) -> date | None:
        pattern = (
            r"\b" + label +
            r"\s*:\s*(?:(?!\b(?:Start|End|Početak|Kraj)\s*:).){0,110}?"
            r"\b(20\d\d-\d\d-\d\d)\b"
        )
        found = re.search(pattern, displayed, re.IGNORECASE)
        if found:
            try:
                return date.fromisoformat(found.group(1))
            except ValueError:
                return None
        return None

    start = dated_label("(?:Start|Početak)")
    end = dated_label("(?:End|Kraj)")
    if start is None:
        for node in content.select(".tribe-events-start-date, time[datetime]"):
            raw = node.get("datetime") or node.get("title") or ""
            m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", str(raw))
            if m:
                try:
                    start = date.fromisoformat(m.group(1))
                    break
                except ValueError:
                    pass
    return start, end


def parse_jsonld_events(markup: str, url: str, city_fallback: str = "Нови-Сад") -> list[Event]:
    soup = BeautifulSoup(markup, "html.parser")
    page_start, page_end = visible_event_dates(soup)
    displayed_text = soup.get_text(" ", strip=True)
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
            if page_start and page_start != start.date():
                print("Afisha visitor-facing start date overrides conflicting JSON-LD date.")
                start = datetime.combine(page_start, datetime.min.time(), tzinfo=TZ)
            if page_end and (end is None or page_end != end.date()):
                print("Afisha visitor-facing end date overrides conflicting JSON-LD date.")
                end = datetime.combine(page_end, datetime.max.time().replace(microsecond=0), tzinfo=TZ)
            summary = clean(item.get("description", ""), 450)
            image = item.get("image") or ""
            if not image:
                og = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
                image = og.get("content", "") if og else ""
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url") or ""
            collected.append(Event(
                url=source, title=title, city=city, venue=venue, start=start,
                end=end, description=summary,
                category=clean(item.get("eventAttendanceMode", ""), 35),
                price=event_price(item, displayed_text),
                image=image if isinstance(image, str) and image.startswith("https://") else "",
                ticket_url=find_ticket_link(soup, item, source),
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
                price=(lambda p: PRICE_UNKNOWN if p.casefold() in ("", "стоимость уточняется", "цена не указана", "не указана") else p)(clean(row.get("price", ""), 75)),
                image=str(row.get("image", "")),
                image_permission=row.get("image_permission") is True,
                ticket_url=safe_ticket_url(str(row.get("ticket_url", "")), url),
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
    venue = ""
    if event.venue:
        location_name = event.venue.strip()
        venue = "\n🏛 <b>Место проведения:</b> " + html.escape(location_name)
        if "skcns" in location_name.casefold() and "fabrika" in location_name.casefold():
            venue += "\n🗺 <b>Адрес:</b> Bulevar despota Stefana 5"
    link = html.escape(event.url, quote=True)
    ticket = safe_ticket_url(event.ticket_url, event.url)
    ticket_line = (
        f'\n🎟 <a href="{html.escape(ticket, quote=True)}">Купить билеты</a>'
        if ticket else ""
    )
    return (
        f"🎭 <b>{title}</b>\n\n"
        f"📅 <b>Дата:</b> {when}\n"
        f"📍 <b>Город:</b> {html.escape(event.city)}{venue}\n"
        f"🎟 <b>Цена:</b> {html.escape(event.price)}\n\n"
        f"📝 {description[:500]}\n\n"
        f'🔗 <a href="{link}">Подробности</a>{ticket_line}'
    )


def load_seen() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def event_topic(event: Event) -> str:
    title = (event.title + " " + event.description[:130]).casefold()
    groups = (
        ("family", ("deca", "decji", "dečji", "children", "kids", "family", "porodic", "детск", "семей")),
        ("festival", ("festival", "фестив", "manifestacij")),
        ("concert", ("koncert", "concert", "muzik", "music", "концерт", "музык")),
        ("theatre", ("theatre", "theater", "pozoriš", "pozoris", "представлен", "театр")),
        ("fair", ("sajam", "fair", "market", "ярмарк", "базар")),
        ("exhibition", ("izložb", "izlozb", "exhibit", "gallery", "izlozba", "выстав", "музе")),
        ("workshop", ("radionic", "workshop", "мастер-класс")),
    )
    for kind, words in groups:
        if any(x in title for x in words):
            return kind
    return "other"


def posted_today(seen: dict, now: datetime) -> list[dict]:
    result = []
    for row in seen.values():
        if not isinstance(row, dict):
            continue
        stamp = parse_date(row.get("published_at"))
        if stamp and stamp.astimezone(TZ).date() == now.astimezone(TZ).date():
            result.append(row)
    return result


def interest_score(event: Event, now: datetime) -> int:
    """Conservative editorial sorting before AI checks quality and writes copy."""
    # A complete event page scores better than a vague one-line promotion.
    text_size = len(clean(event.description, 600))
    score = 22
    if text_size >= 110:
        score += 17
    elif text_size >= 60:
        score += 11
    elif text_size >= 35:
        score += 6
    elif text_size < 20:
        score -= 9
    if event.city in ('Белград', 'Нови-Сад'):
        score += 9  # primary readership, not a filter for other cities
    elif event_topic(event) in ('festival', 'fair', 'concert'):
        score += 5  # worthwhile events can justify travel
    if event.venue:
        score += 12
    else:
        score -= 4
    topic = event_topic(event)
    score += {
        "family": 14, "festival": 15, "concert": 14,
        "theatre": 11, "fair": 13, "exhibition": 10,
        "workshop": 9, "other": 3,
    }[topic]
    days = (event.start.date() - now.date()).days
    if 0 <= days <= 7:
        score += 16
    elif 8 <= days <= 21:
        score += 11
    elif 22 <= days <= 30:
        score += 5
    elif days < 0 and event.end and event.end.date() >= now.date():
        # Long-running exhibitions can be interesting, but prioritize new events.
        score += 4 if days >= -7 else -10
    return score


def select(events: list[Event], seen: dict, now: datetime) -> list[Event]:
    """Rank by useful details, novelty, type and near-term date, never random order."""
    daily = posted_today(seen, now)
    if len(daily) >= MAX_DAILY_POSTS:
        return []
    posted_topics = [r.get("topic", "") for r in daily]
    deduped = {
        e.key: e for e in events
        if e.key not in seen and event_in_window(e, now)
    }
    scored = []
    for e in deduped.values():
        topic = event_topic(e)
        penalty = posted_topics.count(topic) * 9 if topic != "other" else 0
        score = interest_score(e, now) - penalty
        if score >= MIN_INTEREST_SCORE:
            scored.append((score, e))
    scored.sort(key=lambda pair: (
        -pair[0], max((pair[1].start.date()-now.date()).days, 0),
        pair[1].title,
    ))
    return [e for _, e in scored[:SELECTION_POOL]]


def _official_poster(url: str) -> bool:
    """Official tourist organisation's promotional event photo."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in ("novisad.travel", "www.novisad.travel")
        and not parsed.username
        and not parsed.password
    )


def publish(session: requests.Session, token: str, chat: str, post: str,
            source_url: str, image_url: str = "") -> bool:
    """Send an official event poster with a Russian caption; never link previews.

    Fallback is a plain post with link previews disabled.
    """
    api = f"https://api.telegram.org/bot{token}/"
    if image_url and _official_poster(image_url) and len(clean(post, 2000)) <= 1024:
        try:
            photo = session.post(
                api + "sendPhoto",
                json={
                    "chat_id": chat, "photo": image_url,
                    "caption": post, "parse_mode": "HTML",
                    "show_caption_above_media": False,
                },
                timeout=24,
            )
            if photo.ok and photo.json().get("ok") is True:
                print("Official event poster published with Russian caption; no link preview.")
                return True
            print("Official photo wasn't accepted; using text fallback.")
        except (requests.RequestException, ValueError):
            print("Event poster couldn't be sent; using text fallback.")
    try:
        result = session.post(
            api + "sendMessage",
            json={
                "chat_id": chat,
                "parse_mode": "HTML",
                "text": post,
                "link_preview_options": {"is_disabled": True},
            },
            timeout=22,
        )
        if result.ok:
            return result.json().get("ok") is True
        print(f"Telegram status {result.status_code}; check AFISHA_CHAT_ID and bot rights.")
    except (requests.RequestException, ValueError):
        print("Telegram send failed.")
    return False

def publication_allowed(now: datetime, *, initial: bool = False, seen: dict | None = None) -> bool:
    """No publications 22:00–07:59 in Serbia, except one explicitly requested test.

    The test exemption expires automatically after 2026-11-13 07:59 and never
    applies if the channel already has a recorded Afisha publication.
    """
    local = now.astimezone(TZ)
    if 8 <= local.hour < 22:
        return True
    return (
        initial
        and local.date() == FIRST_POST_ONLY_DATE
        and local.hour < 8
        and not seen
    )


def main() -> int:
    now = datetime.now(TZ)
    initial = os.getenv("AFISHA_FIRST_POST_ONCE", "") == "1"
    seen = load_seen()
    if initial and seen:
        print("One-time first Afisha post has already been recorded. Skipping.")
        return 0
    if not publication_allowed(now, initial=initial, seen=seen):
        print("Afisha quiet hours 22:00–08:00 Europe/Belgrade. No publication.")
        return 0
    token = os.getenv("AFISHA_BOT_TOKEN", "").strip()
    chat = os.getenv("AFISHA_CHAT_ID", "").strip()
    dry = os.getenv("AFISHA_DRY_RUN") == "1"
    if not dry and not (token and chat):
        print("AFISHA_BOT_TOKEN or AFISHA_CHAT_ID not set; no publication.")
        return 0
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    daily_count = len(posted_today(seen, now))
    if daily_count >= MAX_DAILY_POSTS:
        print(f"Daily Afisha cap reached: {daily_count}/{MAX_DAILY_POSTS}.")
        return 0
    from belgrade_events import collect_belgrade_events
    events = (
        load_curated_events(now)
        + collect_official_events(session, now)
        + collect_belgrade_events(session, now)
    )
    shortlisted = select(events, seen, now)
    print(f"Event candidates: {len(events)}, ranked shortlist: {len(shortlisted)}, "
          f"today already: {daily_count}/{MAX_DAILY_POSTS}.")
    published = False
    for event in shortlisted[:5]:
        # Require AI editorial approval and an adequate interest score.
        approved = edit_event(event)
        if approved is None:
            continue
        post = format_event(event, approved.title_ru, approved.summary_ru)
        if not publication_allowed(datetime.now(TZ), initial=initial, seen=seen):
            print("Publication blocked: quiet hours started before message could be sent.")
            return 0
        if dry:
            print(f"AI approved via {approved.provider}, score {approved.interest_score}.")
            print(post)
            published = True
            break
        if publish(session, token, chat, post, event.url, event.image):
            seen[event.key] = {
                "url": event.url,
                "event_start": event.start.isoformat(),
                "published_at": now.isoformat(),
                "topic": event_topic(event),
                "ai_editor": approved.provider,
            }
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf8")
            print(f"One quality Afisha event published. AI editor: {approved.provider}.")
            published = True
            break  # maximum one per check; maximum 5 per Belgrade calendar day
        return 1
    if not published:
        print("No editorially approved event; quality over quantity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
