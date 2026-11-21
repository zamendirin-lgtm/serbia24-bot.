"""Serbia 24 | Afisha: independent, source-linked Serbia event announcements.

First source: Novi Sad Tourism Organisation's public events calendar. Only brief
factual metadata is used; original event media is represented by a link preview,
not copied. Curated, owner-authorized JSON is accepted for other Serbian cities.
"""
from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from afisha_editor import edit_event
from afisha_photos import find_licensed_photo
from afisha_context import contextual_lines
from afisha_cards import branded_poster

TZ = ZoneInfo("Europe/Belgrade")
STATE = Path("data/afisha_seen.json")
BASE = "https://novisad.travel"
SOURCE = BASE + "/en/kalendar-dogadjaja/kategorija/calendar-of-events/list/"
UA = "Serbia24Afisha/1.0 (+https://github.com/zamendirin-lgtm/serbia24-bot.)"
MAX_LINKS = 32
MAX_POSTS = 1  # only one good event per run
PRICE_UNKNOWN = "не указана"
MAX_DAILY_POSTS = 6
SELECTION_POOL = 24
# Six non-overlapping publication slots match the six GitHub Actions runs.
# They map to roughly 08-20 local time in winter and 09-21 in summer.
SLOT_STARTS_UTC = (7, 9, 11, 14, 17, 19)
# Eleven editorial themes roll forward by six slots per day. The full range
# is covered across days rather than requiring all genres on the same day.
TOPIC_CYCLE = (
    "family", "concert", "theatre", "exhibition", "comedy", "workshop",
    "classical", "festival", "cinema", "fair", "nightlife",
)
TOPIC_CYCLE_START = date(2026, 11, 21)
MARQUEE_LOOKAHEAD_DAYS = 300
MONTHLY_REMINDER_DAYS = 30
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


def official_event_poster(soup: BeautifulSoup, item: dict, page_url: str) -> str:
    """Find the actual event cover on the tourism organiser's page.

    JSON-LD can omit Event.image despite a poster being shown on the page.
    Prefer the single-event cover; accept only HTTPS image files hosted by the
    tourism organisation, not remote photos, logos or unrelated content.
    """
    candidates = []
    for node in soup.select(
        ".tribe-events-event-image img, "
        ".tribe-events-single-event-description .tribe-events-event-image img"
    ):
        for attr in ("data-src", "data-lazy-src", "src"):
            value = node.get(attr)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

    structured = item.get("image") or ""
    if isinstance(structured, list):
        structured = structured[0] if structured else ""
    if isinstance(structured, dict):
        structured = structured.get("url") or structured.get("contentUrl") or ""
    if isinstance(structured, str):
        candidates.append(structured)

    for node in soup.select('meta[property="og:image"], meta[name="twitter:image"]'):
        candidates.append(node.get("content", ""))

    for value in candidates:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = urljoin(page_url, value.strip())
        if _official_poster(candidate):
            return candidate
    return ""


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
            image = official_event_poster(soup, item, url)
            collected.append(Event(
                url=source, title=title, city=city, venue=venue, start=start,
                end=end, description=summary,
                category=clean(item.get("eventAttendanceMode", ""), 35),
                price=event_price(item, displayed_text),
                image=image,
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


def is_marquee_event(event: Event) -> bool:
    """Require strong, attributable evidence before allowing early announcements.

    Recognised large festivals may be promoted months ahead. Other culture
    events qualify only at major venues with a real event page, substantive
    description and a poster or verified ticket link. An arbitrary 'festival'
    listing should not trigger monthly reminders.
    """
    title = clean(event.title, 150).casefold()
    venue = clean(event.venue, 140).casefold()
    source = (urlparse(event.url).hostname or "").removeprefix("www.")
    festival_name = re.search(
        r"\b(?:exit(?:\s+festival)?|nisville|nišville|lovefest|beer\s*fest|"
        r"arsenal\s*fest|guča|guca|bemus|filmski\s+festival\s+fest)\b",
        title, re.IGNORECASE,
    ) is not None
    if festival_name and (source == "exitfest.org" or (
        len(clean(event.description, 500)) >= 65 and
        bool(event.city) and bool(event.venue)
    )):
        return True
    major_hosts = (
        "savacentar.rs", "arenabeograd.com", "prodaja.snp.org.rs",
    )
    major_venues = (
        "сaва центар", "сава центар", "sava centar", "plava dvorana",
        "beogradska arena", "белградская арена",
        "mts dvorana", "dom omladine", "kolarac", "коларац",
        "srpsko narodno", "сербский национальный театр",
        "spens", "спенс",
    )
    cultural = event_topic(event) in ("festival", "concert", "theatre", "family")
    return (
        cultural and len(clean(event.description, 600)) >= 75
        and (bool(event.image) or bool(event.ticket_url))
        and (source in major_hosts or any(v in venue for v in major_venues))
    )


def event_in_window(event: Event, now: datetime) -> bool:
    local_today = now.astimezone(TZ).date()
    if event.end and event.end < event.start:
        return False
    if event.end:
        if event.end.astimezone(TZ).date() < local_today:
            return False
    elif event.start.astimezone(TZ).date() < local_today:
        return False
    limit = MARQUEE_LOOKAHEAD_DAYS if is_marquee_event(event) else 75
    return event.start.astimezone(TZ).date() <= local_today + timedelta(days=limit)


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


def normalize_sava_hall(venue: str) -> str:
    """Keep the real Russian name of Sava Centar's Plava dvorana (Blue Hall)."""
    raw = clean(venue, 140)
    if (
        re.search(r"(?:sava\s*centar|сава\s*цент[а-я]*)", raw, re.IGNORECASE)
        and re.search(
            r"(?:plav[a-z]*\s+(?:dvoran[a-z]*|sal[a-z]*)|"
            r"плав[а-я]*\s+зал[а-я]*|син[а-я]*\s+зал[а-я]*)",
            raw, re.IGNORECASE,
        )
    ):
        return "Сава Центар, Синий зал (Plava dvorana)"
    return raw


def normalize_sava_description(description: str) -> str:
    """Fix the recurring mangled hall name in AI-written Russian descriptions."""
    value = re.sub(
        r"\bв\s+Сава\s+Центре\s*,\s*Плав[а-я]*\s+зал[а-я]*",
        "в Синем зале «Сава Центра»",
        description,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\bПлав[а-я]*\s+зал[а-я]*",
        "Синий зал",
        value,
        flags=re.IGNORECASE,
    )
    return value


AFISHA_FOOTER_HASHTAG = "#Сербия24"


def finalize_afisha_post(post: str, photo_credit: str = "") -> str:
    """Keep one clickable Telegram hashtag as the very last line.

    A verified Commons photo's short linked camera icon must appear BEFORE the
    hashtag, not after it. The helper is also used at the Telegram send boundary,
    so even future nonstandard posting paths retain the channel footer.
    """
    clean_post = re.sub(r"(?:\s*#Сербия24\s*)+$", "", post).rstrip()
    if photo_credit:
        clean_post += "\n" + photo_credit.strip()
    return clean_post + "\n\n" + AFISHA_FOOTER_HASHTAG


def format_event(event: Event, title_ru: str = "", description_ru: str = "", *, reminder: bool = False) -> str:
    title = html.escape(title_ru or event.title)
    description = html.escape(normalize_sava_description(description_ru)) if description_ru else (
        "Подробная программа и условия — на странице организатора."
    )
    if event.end and event.end.date() != event.start.date():
        when = f"{event.start:%d.%m.%Y}–{event.end:%d.%m.%Y}"
    else:
        when = event.start.strftime("%d.%m.%Y")
        if event.start.hour or event.start.minute:
            when += event.start.strftime(" в %H:%M")
    # Fact-checked two-show schedule: both Sava Centar and Tickets.rs
    # list the 20 December 2026 Nutcracker at 15:00 AND 20:00.
    if (
        "savacentar.rs" in urlparse(event.url).netloc.lower()
        and event.start.strftime("%Y-%m-%d") == "2026-12-20"
        and "krcko" in event.title.casefold()
    ):
        when = "20.12.2026, в 15:00 и 20:00"
    venue = ""
    if event.venue:
        location_name = normalize_sava_hall(event.venue)
        venue = "\n🏛 <b>Место проведения:</b> " + html.escape(location_name)
        if "skcns" in location_name.casefold() and "fabrika" in location_name.casefold():
            venue += "\n🗺 <b>Адрес:</b> Bulevar despota Stefana 5"
    link = html.escape(event.url, quote=True)
    ticket = safe_ticket_url(event.ticket_url, event.url)
    ticket_line = (
        f'\n🎟 <a href="{html.escape(ticket, quote=True)}">Купить билеты</a>'
        if ticket else ""
    )
    context = contextual_lines(event)
    context_line = ("\n" + "\n".join(context)) if context else ""
    return finalize_afisha_post(
        (f"🔔 <b>Напоминаем о предстоящем событии</b>\n\n" if reminder else "")
        + f"🎭 <b>{title}</b>\n\n"
        f"📅 <b>Дата:</b> {when}\n"
        f"📍 <b>Город:</b> {html.escape(event.city)}{venue}\n"
        f"🎟 <b>Цена:</b> {html.escape(event.price)}{context_line}\n\n"
        f"📝 {description[:500]}\n\n"
        f'🔗 <a href="{link}">Подробности</a>{ticket_line}'
        + (f'\n<a href="{link}">📷</a>' if event.image and urlparse(event.url).hostname in (
            "savacentar.rs", "www.savacentar.rs", "novisad.travel", "www.novisad.travel",
            "arenabeograd.com", "www.arenabeograd.com",
            "lozionica.rs", "www.lozionica.rs"
        ) else "")
    )


def load_seen() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}



def is_routine_sports_fixture(event: Event) -> bool:
    """Block regular competitive matches, not sport-themed cultural events.

    RUN BGD also lists EuroLeague, ABA league, football and volleyball games.
    A schedule of team fixtures belongs in a sports channel, not an Afisha
    centred on concerts, festivals, exhibitions and family activities.
    Requiring a sport context AND a match cue avoids blocking an exhibition
    on basketball history, a sports fair, or a concert at a sports arena.
    """
    title = clean(event.title, 220).casefold()
    category = clean(event.category, 90).casefold()
    description = clean(event.description, 450).casefold()
    joined = " ".join((title, category, description))
    sport_context = re.search(
        r"\b(?:euroleague|euro\s*league|evroliga|evroligi|евролиг[а-я]*|"
        r"aba[\s-]*liga|aba[\s-]*league|аба[\s-]*лиг[а-я]*|"
        r"eurocup|euroliga|fiba|uefa|nba|"
        r"basketball|košark[aeiu]?|kosark[aeiu]?|баскетбол[а-я]*|"
        r"football|soccer|fudbal[a-z]*|футбол[а-я]*|"
        r"volleyball|odbojka|волейбол[а-я]*|"
        r"handball|rukomet|гандбол[а-я]*|"
        r"hockey|hokej|хокке[а-я]*|"
        r"superliga|суперлиг[а-я]*|"
        r"sport(?:s|ski|ska|sko)?|спорт[а-я]*)\b",
        joined, re.IGNORECASE,
    ) is not None
    fixture = re.search(
        r"\b(?:vs\.?|versus|against|protiv|против|"
        r"utakmic[a-zčć]*|match(?:es)?|derby|derbi|meč|mec|меч|матч[а-я]*|"
        r"game|round|kolo|кол[а-я]*|тур[а-я]*)\b",
        joined, re.IGNORECASE,
    ) is not None
    return bool(sport_context and fixture)


def event_topic(event: Event) -> str:
    """Classify concrete leisure genres, suitable for all ages and interests."""
    primary = (event.title + " " + event.category).casefold()
    context = event.description[:130].casefold()
    groups = (
        ("family", ("deca", "decji", "dečji", "children", "kids", "family", "porodic",
                    "детск", "семей", "дошколь", "cirkus", "circus", "цирк",
                    "mađionič", "magic show", "magični show", "фокусник", "иллюзион")),
        ("comedy", ("standup", "stand-up", "stand up", "стендап", "стэнд-ап",
                    "komed", "comedy", "комед", "improv", "импровиз", "humor")),
        ("classical", ("simfonij", "simfon", "symphon", "симфони", "orkestar",
                       "orchestra", "оркестр", "filharmon", "филармон",
                       "klasič", "klasicn", "классическ", "jazz", "džez",
                       "джаз", "опера", "opera")),
        ("theatre", ("theatre", "theater", "pozoriš", "pozoris", "представлен",
                     "театр", "balet", "ballet", "балет", "мюзикл", "musical")),
        ("cinema", ("film", "bioskop", "cinema", "кино", "кинопоказ", "projekcij")),
        ("nightlife", ("dj set", "diskot", "žurka", "zurka", "журка",
                       "rave", "рейв", "techno", "техно", "ночной клуб")),
        ("festival", ("festival", "фестив", "manifestacij")),
        ("fair", ("sajam", "fair", "market", "ярмарк", "базар", "gastronom")),
        ("exhibition", ("izložb", "izlozb", "izlozba", "exhibit", "gallery",
                        "выстав", "музе", "galerij")),
        ("workshop", ("radionic", "workshop", "мастер-класс", "творческ",
                      "лекция", "лекции", "lecture", "киноклуб", "vr ",
                      "иммерсив", "экскурс", "эксперимент")),
        ("concert", ("koncert", "concert", "muzik", "music", "концерт",
                     "музык", "nastup", "сольный")),
    )
    # The advertised event category wins over supporting text: a ballet
    # stays theatre even when its description mentions an orchestra.
    for content in (primary, context):
        for kind, words in groups:
            if any(x in content for x in words):
                return kind
    return "other"


def posting_slot(now: datetime) -> int | None:
    """Slot index for the running schedule (accounts for Belgrade daylight saving)."""
    local = now.astimezone(TZ)
    if not 8 <= local.hour < 22:
        return None
    utc_hour = now.astimezone(timezone.utc).hour
    for slot in range(len(SLOT_STARTS_UTC) - 1, -1, -1):
        if utc_hour >= SLOT_STARTS_UTC[slot]:
            return slot
    return None


def target_topic(now: datetime) -> str | None:
    """Rotate all editorial themes over successive days and publication slots."""
    slot = posting_slot(now)
    if slot is None:
        return None
    days = (now.astimezone(TZ).date() - TOPIC_CYCLE_START).days
    return TOPIC_CYCLE[(days * MAX_DAILY_POSTS + slot) % len(TOPIC_CYCLE)]


def slot_already_used(seen: dict, now: datetime) -> bool:
    """Do not use the backup run to post twice in the same editorial slot."""
    slot = posting_slot(now)
    if slot is None:
        return False
    for entry in posted_today(seen, now):
        previous = parse_date(entry.get("published_at"))
        if previous and posting_slot(previous) == slot:
            return True
    return False


def posted_today(seen: dict, now: datetime) -> list[dict]:
    result = []
    for row in seen.values():
        if not isinstance(row, dict) or row.get("corrected_test") is True or row.get("digest_item") is True:
            continue
        stamp = parse_date(row.get("published_at"))
        if stamp and stamp.astimezone(TZ).date() == now.astimezone(TZ).date():
            result.append(row)
    return result


def post_spacing_ok(seen: dict, now: datetime, minutes: int = 90) -> bool:
    """Protect channel from near-simultaneous main and backup scheduled runs."""
    for row in seen.values():
        if not isinstance(row, dict) or row.get("corrected_test") is True or row.get("digest_item") is True:
            continue
        stamp = parse_date(row.get("published_at"))
        if stamp:
            diff = now - stamp.astimezone(TZ)
            if timedelta(0) <= diff < timedelta(minutes=minutes):
                return False
    return True


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
    elif event_topic(event) in ('festival', 'fair', 'concert', 'classical', 'theatre'):
        score += 5  # worthwhile events can justify travel
    if event.venue:
        score += 12
    else:
        score -= 4
    if event.ticket_url:
        score += 7
    if event.image:
        score += 9
    if "savacentar.rs" in urlparse(event.url).netloc.lower():
        score += 12  # verified flagship venue programmes, not generic sports
    # Major halls have greater relevance for our cultural event readership.
    # Sporting matches remain filtered out *before* ranking.
    major = (
        "beogradska arena", "белградская арена", "sava centar",
        "сава центар", "mts dvorana", "мтс дворана", "dom omladine",
        "дом омладине", "kolarac", "коларац", "srpsko narodno",
        "сербский национальный театр", "spens", "спенс",
    )
    if any(term in (event.venue + " " + event.url).casefold() for term in major):
        score += 16
    if any(k in (event.title + " " + event.category).casefold()
           for k in ("ballet", "balet", "балет", "opera", "опер", "мюзикл", "musical")):
        score += 14  # family stage productions deserve longer lead times
    topic = event_topic(event)
    score += {
        "family": 14, "festival": 15, "concert": 14,
        "theatre": 11, "fair": 13, "exhibition": 10,
        "workshop": 9, "comedy": 12, "classical": 14,
        "cinema": 11, "nightlife": 11, "other": 3,
    }[topic]
    if is_marquee_event(event):
        score += 14  # allow distant headline events to clear quality threshold
    # Give smaller real-life experiences room beside large concert halls.
    if (topic in ("workshop", "family", "exhibition", "theatre")
        and urlparse(event.url).hostname in ("lozionica.rs", "www.lozionica.rs", "afisha.rs", "www.afisha.rs")
        and 0 <= (event.start.date() - now.date()).days <= 14):
        score += 10
    days = (event.start.date() - now.date()).days
    if 0 <= days <= 7:
        score += 16
    elif 8 <= days <= 21:
        score += 11
    elif 22 <= days <= 30:
        score += 5
    elif 31 <= days <= 75:
        score += 3
    elif days < 0 and event.end and event.end.date() >= now.date():
        # Long-running exhibitions can be interesting, but prioritize new events.
        score += 4 if days >= -7 else -10
    return score


def event_series_key(url: str) -> str:
    """Do not reannounce the same multiday Belgrade exhibition every day."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    path = parsed.path.rstrip("/")
    if parsed.hostname in ("runbgd.com", "www.runbgd.com") and path.startswith("/whats-on/"):
        path = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", path)
    return (parsed.hostname or "") + path


def _event_slug(url: str) -> tuple[str, str, str]:
    """Extract source host, event slug and its optional ISO date from a URL."""
    try:
        p = urlparse(url)
    except ValueError:
        return "", "", ""
    host = (p.hostname or "").removeprefix("www.")
    slug = p.path.rstrip("/").rsplit("/", 1)[-1].casefold()
    match = re.search(r"-(20\d{2}-\d{2}-\d{2})$", slug)
    occurrence = match.group(1) if match else ""
    if match:
        slug = slug[:match.start()]
    return host, slug, occurrence


def same_real_event(event: Event, previous: dict) -> bool:
    """Detect slightly different RUN BGD slugs for the *same* dated event.

    Example source aliases:
      jelena-radanovic-novi-show-druzina-ljubavi-2026-11-17
      jelena-radanovic-novi-show-duzna-u-ljubavi-2026-11-17

    The URL hashes differ, but performer, show, date and venue are the same.
    Require a matching date and very close distinctive slug; never collapse
    multiple separate shows merely because a musician or date matches.
    """
    if not isinstance(previous, dict) or not previous.get("url"):
        return False
    prev_url = str(previous["url"])
    if event_series_key(event.url) == event_series_key(prev_url):
        return True
    # Major venues often give the 15:00 and 20:00 shows different page URLs.
    # One production/date/venue should be announced once with both times.
    new_host = (urlparse(event.url).hostname or "").removeprefix("www.")
    old_host = (urlparse(prev_url).hostname or "").removeprefix("www.")
    if new_host == old_host == "savacentar.rs" and previous.get("title"):
        earlier = parse_date(previous.get("event_start"))
        if (
            earlier is not None and earlier.date() == event.start.date()
            and clean(previous["title"], 120).casefold() == clean(event.title, 120).casefold()
            and clean(previous.get("venue", ""), 130).casefold() == event.venue.casefold()
        ):
            return True
    host, slug, url_date = _event_slug(event.url)
    prev_host, prev_slug, prev_date = _event_slug(prev_url)
    if host != prev_host or host not in ("runbgd.com",) or not slug or not prev_slug:
        return False
    stamp = parse_date(previous.get("event_start"))
    if stamp and stamp.date() != event.start.date():
        return False
    # Only compare source slug aliases for a known same-day event.
    if (url_date and url_date != event.start.date().isoformat()) or (
        prev_date and prev_date != event.start.date().isoformat()
    ):
        return False
    if not (url_date and prev_date) and not stamp:
        return False
    if previous.get("city") and previous["city"].strip().casefold() != event.city.strip().casefold():
        return False
    if previous.get("venue") and previous["venue"].strip().casefold() != event.venue.strip().casefold():
        return False
    a, b = slug.split("-"), prev_slug.split("-")
    if len(a) < 5 or len(b) < 5:
        return False
    # Require the same performer/show prefix and distinctive last word, not
    # merely "Jelena Radanovic" playing two separate gigs.
    if a[:4] != b[:4] or a[-1] != b[-1] or len(a[-1]) < 5:
        return False
    # Different show numbers/editions are distinct, despite similar slugs.
    if [w for w in a if w.isdigit()] != [w for w in b if w.isdigit()]:
        return False
    return SequenceMatcher(None, slug, prev_slug).ratio() >= 0.90


def same_edition(event: Event, previous: dict) -> bool:
    """Same real dated event, even if published under another source URL.

    A different year or different date is a new occurrence, not a duplicate.
    Old bot records may lack title/venue, but always contain a source URL.
    """
    if not isinstance(previous, dict) or previous.get("corrected_test"):
        return False
    old_start = parse_date(previous.get("event_start"))
    source_series = event_series_key(str(previous.get("url", "")))
    current_series = event_series_key(event.url)
    # Older history records sometimes contain URL only. Fail closed when
    # the same source series was already published, instead of reposting.
    if not old_start:
        return bool(previous.get("url") and source_series == current_series)
    # Multiple dated records from a single exhibition aren't new events.
    # An exhibition in a DIFFERENT year is a new annual edition.
    if (
        source_series == current_series
        and (event_topic(event) == "exhibition" or previous.get("topic") == "exhibition")
        and old_start.year == event.start.year
    ):
        return True
    if old_start.astimezone(TZ).date() != event.start.astimezone(TZ).date():
        return False
    if same_real_event(event, previous):
        return True
    if (previous.get("title") and previous.get("venue")
        and clean(str(previous["title"]), 130).casefold() == clean(event.title, 130).casefold()
        and clean(str(previous["venue"]), 130).casefold() == clean(event.venue, 130).casefold()
        and clean(str(previous.get("city", "")), 90).casefold() == clean(event.city, 90).casefold()):
        return True
    return False


def edition_history(event: Event, seen: dict) -> list[dict]:
    return [row for row in seen.values() if same_edition(event, row)]


def monthly_reminder_due(event: Event, seen: dict, now: datetime) -> bool:
    """Monthly reminders for genuinely major events, never for routine gigs."""
    history = edition_history(event, seen)
    if not history or not is_marquee_event(event):
        return False
    if event.start.astimezone(TZ).date() <= now.astimezone(TZ).date():
        return False
    dates = [parse_date(row.get("published_at")) for row in history]
    # If publication dates are missing, fail closed rather than spam.
    if not dates or any(d is None for d in dates):
        return False
    return (now - max(dates)).total_seconds() >= MONTHLY_REMINDER_DAYS * 86400


def eligible_for_post(event: Event, seen: dict, now: datetime) -> bool:
    if not event_in_window(event, now) or is_routine_sports_fixture(event):
        return False
    history = edition_history(event, seen)
    # Legacy state can have an event hash without complete row metadata.
    # Treat it as posted, rather than bypassing duplicate protection.
    if event.key in seen and not history:
        return False
    return not history or monthly_reminder_due(event, seen, now)


def select(events: list[Event], seen: dict, now: datetime) -> list[Event]:
    """Choose verified events with a multi-day rotation of leisure genres.

    The target genre receives priority only among events meeting the usual
    relevance threshold. If nothing good exists for a genre, use a strong
    alternative instead of fabricating or repeating an announcement.
    """
    daily = posted_today(seen, now)
    if len(daily) >= MAX_DAILY_POSTS:
        return []
    posted_topics = [r.get("topic", "") for r in daily]
    posted_venues = [str(r.get("venue", "")).casefold() for r in daily]
    posted_cities = [str(r.get("city", "")).casefold() for r in daily]
    posted_free = sum(1 for r in daily if r.get("is_free") is True)
    posted_hosts = [urlparse(str(r.get("url", ""))).hostname for r in daily]
    recent_topic_counts = {}
    for row in seen.values():
        if not isinstance(row, dict) or row.get("corrected_test"):
            continue
        stamp = parse_date(row.get("published_at"))
        if stamp and timedelta(0) <= now - stamp <= timedelta(days=3):
            topic = row.get("topic", "")
            if topic:
                recent_topic_counts[topic] = recent_topic_counts.get(topic, 0) + 1

    desired_topic = target_topic(now)
    deduped = {}
    for event in events:
        if not eligible_for_post(event, seen, now):
            continue
        series = event_series_key(event.url)
        key = (series, "exhibition" if event_topic(event) == "exhibition"
               else event.start.astimezone(TZ).date())
        if key in deduped:
            continue
        if any(same_edition(event, {
            "url": other.url, "event_start": other.start.isoformat(),
            "title": other.title, "city": other.city, "venue": other.venue,
        }) for other in deduped.values()):
            continue
        deduped[key] = event

    scored = []
    for event in deduped.values():
        topic = event_topic(event)
        base = interest_score(event, now)
        days = (event.start.astimezone(TZ).date() - now.astimezone(TZ).date()).days
        # Still require a worthwhile event before considering the rotation.
        if days > 75:
            base -= 16
        if monthly_reminder_due(event, seen, now):
            base -= 15
        if base < MIN_INTEREST_SCORE:
            continue
        score = base
        if topic == desired_topic:
            score += 65
        score -= posted_topics.count(topic) * 24
        score -= recent_topic_counts.get(topic, 0) * 6
        if event.venue:
            score -= posted_venues.count(event.venue.casefold()) * 12
        score -= posted_hosts.count(urlparse(event.url).hostname) * 5
        score -= posted_cities.count(event.city.casefold()) * 5
        # Accessible free events deserve airtime beside ticketed concerts,
        # but unknown prices are NEVER classified as free.
        if event.price.startswith("Бесплатно") and posted_free == 0:
            score += 12
        if now.astimezone(TZ).weekday() in (3, 4):
            # Thursday/Friday: emphasize immediate weekend plans without
            # claiming that older far-off concerts are newly announced.
            gap = (event.start.astimezone(TZ).date() - now.astimezone(TZ).date()).days
            if 0 <= gap <= 3 and event.start.astimezone(TZ).weekday() in (5, 6):
                score += 8
        scored.append((score, event))

    scored.sort(key=lambda item: (
        -item[0],
        max((item[1].start.astimezone(TZ).date() - now.astimezone(TZ).date()).days, 0),
        item[1].title,
    ))
    # Put at most two candidates per genre in the first editorial pass.
    # This makes AI rejection of one listing less likely to monopolize the run.
    shortlist, overflow, per_topic = [], [], {}
    for _, event in scored:
        topic = event_topic(event)
        if per_topic.get(topic, 0) >= 2:
            overflow.append(event)
        else:
            shortlist.append(event)
            per_topic[topic] = per_topic.get(topic, 0) + 1
    return (shortlist + overflow)[:SELECTION_POOL]


def _official_poster(url: str) -> bool:
    """Allow the official tourism source's real event image only."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in (
            "novisad.travel", "www.novisad.travel",
            "savacentar.rs", "www.savacentar.rs",
            "arenabeograd.com", "www.arenabeograd.com",
            "lozionica.rs", "www.lozionica.rs",
        )
        and not parsed.username
        and not parsed.password
        and parsed.path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and not any(
            label in parsed.path.casefold() for label in ("logo", "placeholder", "default")
        )
    )


def _send_event_photo(session: requests.Session, api: str, chat: str,
                      caption: str, image_url: str) -> bool:
    """Try Telegram photo-by-URL, then upload validated official image bytes."""
    payload = {
        "chat_id": chat, "photo": image_url,
        "caption": caption, "parse_mode": "HTML",
        "show_caption_above_media": False,
    }
    try:
        sent = session.post(api + "sendPhoto", json=payload, timeout=24)
        if sent.ok and sent.json().get("ok") is True:
            print("Afisha event published as photo with a Russian caption.")
            return True
    except (requests.RequestException, ValueError):
        pass

    # Telegram sometimes cannot fetch a poster URL due to redirects/CDN policy.
    # Upload its image bytes instead, but only after strict source/size checks.
    try:
        downloaded = session.get(image_url, timeout=16)
        downloaded.raise_for_status()
        content = downloaded.content
        if not isinstance(content, bytes) or not (1024 <= len(content) <= 8_000_000):
            print("Official event image was missing or unusually sized.")
            return False
        if content.startswith(b"\\xff\\xd8\\xff"):
            extension, content_type = "jpg", "image/jpeg"
        elif content.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
            extension, content_type = "png", "image/png"
        else:
            print("Official image format is not supported for Telegram photos.")
            return False
        uploaded = session.post(
            api + "sendPhoto",
            data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("event." + extension, content, content_type)},
            timeout=32,
        )
        if uploaded.ok and uploaded.json().get("ok") is True:
            print("Afisha event photo uploaded directly with Russian caption.")
            return True
    except (requests.RequestException, ValueError):
        pass
    return False


def publish(session: requests.Session, token: str, chat: str, post: str,
            source_url: str, image_url: str = "",
            *, licensed_commons: bool = False,
            generated_card: bytes | None = None) -> bool:
    """Use a clean photo with Russian caption or text-only, never foreign previews.

    Telegram link previews pull the source's Serbian/English title and synopsis,
    making a second foreign-language block above the Russian announcement.
    """
    post = finalize_afisha_post(post)
    api = f"https://api.telegram.org/bot{token}/"
    official = _official_poster(image_url)
    commons = (
        licensed_commons
        and urlparse(image_url).scheme == "https"
        and urlparse(image_url).hostname == "upload.wikimedia.org"
    )
    if image_url and (official or commons) and len(post) <= 1024:
        if _send_event_photo(session, api, chat, post, image_url):
            return True
        print("Licensed event image failed; posting Russian text without a link preview.")
    elif image_url and (official or commons):
        print("Long Afisha caption; posting full Russian text without a link preview.")

    # Own-brand artwork is always preferable to a misleading unrelated photo.
    # Keep the full text-only fallback for captions that exceed 1024 chars.
    if generated_card and len(post) <= 1024:
        try:
            sent = session.post(
                api + "sendPhoto",
                data={"chat_id": chat, "caption": post, "parse_mode": "HTML"},
                files={"photo": ("serbia24-afisha.jpg", generated_card, "image/jpeg")},
                timeout=28,
            )
            if sent.ok and sent.json().get("ok") is True:
                print("Afisha published with own-brand event card.")
                return True
        except (requests.RequestException, ValueError):
            print("Branded Afisha card send failed; trying text.")

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
        print(f"Telegram status {result.status_code}; check Afisha chat and bot rights.")
    except (requests.RequestException, ValueError):
        print("Telegram Afisha send failed.")
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
    if posting_slot(now) is None:
        print("Afisha is outside the six scheduled publication slots.")
        return 0
    if slot_already_used(seen, now):
        print("Afisha already published in this slot; no second post.")
        return 0
    if not post_spacing_ok(seen, now):
        print("Afisha last post was less than 90 minutes ago; skipping this check.")
        return 0
    from belgrade_events import collect_belgrade_events
    from subotica_events import collect_subotica_events
    from sava_events import collect_sava_events
    from major_venues import collect_major_venues
    from local_culture_events import collect_local_culture
    from mts_events import collect_mts_events
    sources = [
        ("approved", lambda: load_curated_events(now)),
        ("novi_sad_tourism", lambda: collect_official_events(session, now)),
        ("run_bgd", lambda: collect_belgrade_events(session, now)),
        ("subotica", lambda: collect_subotica_events(session, now)),
        ("sava_centar", lambda: collect_sava_events(session, now)),
        ("arena_and_snp", lambda: collect_major_venues(session, now)),
        ("local_culture", lambda: collect_local_culture(session, now)),
        ("mts_dvorana", lambda: collect_mts_events(session, now)),
    ]
    events, source_health = [], {}
    for name, collector in sources:
        began = time.monotonic()
        try:
            items = collector()
            if not isinstance(items, list):
                raise TypeError("Collector returned non-list")
            events.extend(items)
            source_health[name] = {"count": len(items), "status": "ok"}
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            print(f"Afisha source {name} failed: {type(exc).__name__}.")
            source_health[name] = {"count": 0, "status": "error"}
        source_health[name]["duration_s"] = round(time.monotonic() - began, 2)
    shortlisted = select(events, seen, now)
    try:
        report = {
            "checked_at": now.isoformat(), "sources": source_health,
            "candidate_count": len(events), "shortlist_count": len(shortlisted),
            "posted_today": daily_count, "target_topic": target_topic(now),
        }
        path = Path("reports/afisha_health.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf8")
        print("Afisha health report:", json.dumps(report, ensure_ascii=False))
    except OSError:
        print("Afisha health report could not be written.")
    print(f"Event candidates: {len(events)}, ranked shortlist: {len(shortlisted)}, "
          f"today already: {daily_count}/{MAX_DAILY_POSTS}.")
    # A Friday roundup replaces one ordinary publication, never increases the cap.
    if now.astimezone(TZ).weekday() == 4 and posting_slot(now) == 2:
        from afisha_weekend import maybe_publish_weekend
        if maybe_publish_weekend(session, token, chat, shortlisted, seen, now, dry=dry):
            return 0

    published = False
    for event in shortlisted[:10]:
        # Require AI editorial approval and an adequate interest score.
        approved = edit_event(event)
        if approved is None:
            continue
        reminder = monthly_reminder_due(event, seen, now)
        post = format_event(event, approved.title_ru, approved.summary_ru, reminder=reminder)
        if not publication_allowed(datetime.now(TZ), initial=initial, seen=seen):
            print("Publication blocked: quiet hours started before message could be sent.")
            return 0
        if dry:
            print(f"AI approved via {approved.provider}, score {approved.interest_score}.")
            print(post)
            published = True
            break
        # When no official event poster is available, look for a licensed image
        # of the actual performer or a clearly labelled prior-year event photo.
        # Wikimedia Commons metadata is checked for author and licence.
        chosen_image = event.image
        licensed_commons = False
        if not chosen_image:
            photo = find_licensed_photo(session, event)
            if photo:
                with_credit = finalize_afisha_post(post, photo.credit_html())
                if len(with_credit) <= 1024:
                    post = with_credit
                    chosen_image = photo.image_url
                    licensed_commons = True
                    print(f"Afisha matched {photo.subject_label} from Wikimedia Commons.")
                else:
                    print("Licensed image credit would exceed Telegram caption size; keeping full text.")
        card = None
        if not chosen_image or not _official_poster(chosen_image):
            try:
                card = branded_poster(approved.title_ru, event.city, event.start.strftime("%d.%m.%Y"))
            except (OSError, ValueError):
                print("Branded poster unavailable; full text will still publish.")
        if publish(session, token, chat, post, event.url, chosen_image,
                   licensed_commons=licensed_commons, generated_card=card):
            # Preserve the original event key on first publication, but keep
            # separate history records for monthly reminders of the same edition.
            history_key = (
                hashlib.sha256((event.key + "|" + now.isoformat()).encode("utf8")).hexdigest()
                if reminder else event.key
            )
            seen[history_key] = {
                "url": event.url,
                "event_start": event.start.isoformat(),
                "published_at": now.isoformat(),
                "topic": event_topic(event),
                "ai_editor": approved.provider,
                "title": event.title,
                "city": event.city,
                "venue": event.venue,
                "is_free": event.price.startswith("Бесплатно"),
                "reminder": reminder,
            }
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf8")
            print(f"One quality Afisha event published. AI editor: {approved.provider}.")
            published = True
            break  # one per check and slot; maximum 6 per Belgrade calendar day
        return 1
    if not published:
        print("No editorially approved event; quality over quantity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
