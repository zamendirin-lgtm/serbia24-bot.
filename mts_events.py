"""Official MTS Dvorana events: dated performances, music and family shows.

Read only the published factual metadata and event URLs. No third-party
summaries or off-site photos; check robots.txt and reject ambiguous dates.
The event-specific checkout URL is also an authoritative year/time source.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://mtsdvorana.rs"
CALENDAR = BASE + "/dogadjaji"
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "avg": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}
DATE = re.compile(r"(?<!\d)(\d{1,2})\s+(jan|feb|mar|apr|maj|jun|jul|avg|sep|okt|nov|dec)\b", re.I)
CHECKOUT_DATE = re.compile(r"/(20\d{2})-(\d\d)-(\d\d)-(\d\d)(\d\d)(?:/|$)")
FULL_DATE = re.compile(r"(?<!\d)(\d{1,2})\.\s*([a-zčćšđž]+)\s+(20\d{2})\.", re.I)
LONG_MONTHS = {
    "januar": 1, "februar": 2, "mart": 3, "april": 4, "maj": 5,
    "jun": 6, "jul": 7, "avgust": 8, "septembar": 9,
    "oktobar": 10, "novembar": 11, "decembar": 12,
}


def safe_detail_url(value: str) -> str:
    try:
        p = urlparse(urljoin(CALENDAR, value))
    except (ValueError, TypeError):
        return ""
    if (p.scheme != "https" or p.hostname not in ("mtsdvorana.rs", "www.mtsdvorana.rs")
        or p.username or p.password or not re.fullmatch(r"/dogadjaj/[a-zA-Z0-9-]+/?", p.path)):
        return ""
    return urlunparse(("https", "mtsdvorana.rs", p.path.rstrip("/"), "", "", ""))


def list_event_urls(markup: str) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    found = []
    for link in soup.select('a[href*="/dogadjaj/"]'):
        url = safe_detail_url(link.get("href", ""))
        if url and url not in found:
            found.append(url)
    return found[:70]


def parse_detail(markup: str, url: str, now: datetime):
    """Use exact ticket checkout time if available, otherwise the visible date."""
    from afisha_bot import Event, TZ, clean, event_in_window, safe_ticket_url

    if not safe_detail_url(url):
        return None
    soup = BeautifulSoup(markup, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    title = clean(h1.get_text(" ", strip=True), 110)
    if len(title) < 4:
        return None
    text = soup.get_text(" ", strip=True)
    # Site card contains: "5 dec sub mts Dvorana Predstave Sala 6 12:00 od 600".
    # Restrict dates to the area immediately below the main title.
    header_text = text[:900]
    heading_index = header_text.casefold().find(title.casefold())
    if heading_index >= 0:
        header_text = header_text[heading_index + len(title):]
    about_index = re.search(r"O događaju|O dogadjaju", header_text, re.I)
    if about_index:
        header_text = header_text[:about_index.start()]

    category_match = re.search(r"\b(Predstave|Koncerti|Festivali|Ostalo)\b", header_text)
    category = category_match.group(1) if category_match else ""
    hall_match = re.search(r"\b(Sala\s*\d+|Central Hall)\b", header_text, re.I)
    hall = hall_match.group(1) if hall_match else ""
    venue = "MTS Dvorana" + (", " + hall if hall else "")
    ticket_url = ""
    start = None
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True).casefold()
        if "kupi ulaznicu" not in label and "kupi kartu" not in label:
            continue
        link = safe_ticket_url(urljoin(url, a.get("href", "")), url)
        match = CHECKOUT_DATE.search(urlparse(link).path) if link else None
        if not match:
            continue
        try:
            parts = tuple(int(p) for p in match.groups())
            proposed = datetime(*parts, tzinfo=TZ)
        except ValueError:
            continue
        ticket_url = link
        start = proposed
        break

    if start is None:
        # Full explicit-year dates are safe; otherwise accept only upcoming dates
        # from the venue's current upcoming calendar.
        full = FULL_DATE.search(header_text)
        if full and full.group(2).casefold() in LONG_MONTHS:
            try:
                date_parts = (int(full.group(3)), LONG_MONTHS[full.group(2).casefold()], int(full.group(1)))
                starts = datetime(*date_parts, tzinfo=TZ)
            except ValueError:
                return None
        else:
            match = DATE.search(header_text)
            if not match:
                return None
            try:
                starts = datetime(now.astimezone(TZ).year, MONTHS[match.group(2).casefold()],
                                  int(match.group(1)), tzinfo=TZ)
                if starts.date() < now.astimezone(TZ).date():
                    starts = starts.replace(year=starts.year + 1)
            except ValueError:
                return None
        # Prefer a showtime near the event card, not a contact number in footer.
        time_match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", header_text)
        if not time_match:
            return None
        start = starts.replace(hour=int(time_match.group(1)), minute=int(time_match.group(2)))

    # A card's date must agree with the event-specific ticket page when both exist.
    visible_date = DATE.search(header_text)
    if visible_date and (int(visible_date.group(1)) != start.day
                         or MONTHS[visible_date.group(2).casefold()] != start.month):
        return None

    after = text.split("O događaju", 1)
    summary = clean(after[1].split("Organizator:", 1)[0], 430) if len(after) == 2 else ""
    summary = re.sub(r"\b(?:Pročitaj više|Kupi ulaznicu)\b", "", summary, flags=re.I).strip()
    if len(summary) < 25:
        return None
    price = "не указана"
    listed_price = re.search(r"\bod\s+(\d[\d. ]{0,8})\b", header_text, re.I)
    if listed_price:
        amount = listed_price.group(1).strip()
        if amount and int(re.sub(r"\D", "", amount) or "0") > 0:
            price = "от " + amount + " дин."
    elif re.search(r"besplatan\s+ulaz|ulaz\s+je\s+slobodan", header_text, re.I):
        price = "Бесплатно (по данным организатора)"
    event = Event(
        url=safe_detail_url(url), title=title, city="Белград",
        venue=venue, start=start, description=summary,
        category=category, price=price, ticket_url=ticket_url,
    )
    return event if event_in_window(event, now) else None


def collect_mts_events(session: requests.Session, now: datetime) -> list:
    from afisha_bot import UA
    if os.getenv("AFISHA_ENABLE_MTS", "1") != "1":
        print("MTS Dvorana source disabled.")
        return []
    try:
        response = session.get(BASE + "/robots.txt", timeout=12)
        response.raise_for_status()
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        if not rules.can_fetch(UA, CALENDAR):
            print("MTS Dvorana: calendar not allowed by robots policy.")
            return []
        listing = session.get(CALENDAR, timeout=18)
        listing.raise_for_status()
        if len(listing.content) > 2_000_000:
            print("MTS Dvorana: oversized listing, skipped.")
            return []
    except requests.RequestException as exc:
        print("MTS Dvorana: source unavailable (" + type(exc).__name__ + ").")
        return []

    links = list_event_urls(listing.text)
    print("MTS Dvorana: discovered " + str(len(links)) + " detail links.")
    found = []
    for url in links:
        if not rules.can_fetch(UA, url):
            continue
        try:
            detail = session.get(url, timeout=12)
            detail.raise_for_status()
            if len(detail.content) > 1_800_000:
                continue
            item = parse_detail(detail.text, url, now)
            if item:
                found.append(item)
        except requests.RequestException:
            continue
    print("MTS Dvorana: " + str(len(found)) + " verified upcoming events.")
    return found
