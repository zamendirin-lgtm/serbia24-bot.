"""Smaller Serbian cultural events: Ložionica official, Afisha.rs listings.

Fetch short event facts only, not third-party prose or images. Both adapters
fail closed on robots restrictions, missing dates, stale pages and bad links.
Official Ložionica promotional art is an event-specific poster (not a logo).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from afisha_media import find_official_event_poster

LOZ = "https://lozionica.rs"
LOZ_CALENDAR = LOZ + "/dogadjaji/"
AFISHA = "https://afisha.rs"
AFISHA_CATEGORIES = (
    "/ru/lekcii", "/ru/teatr", "/ru/koncerty", "/ru/vystavki",
    "/ru/master-klassy", "/ru/filmy", "/ru/deti",
)
MONTHS = {
    "januar": 1, "februar": 2, "mart": 3, "april": 4, "maj": 5,
    "jun": 6, "jul": 7, "avgust": 8, "septembar": 9,
    "oktobar": 10, "novembar": 11, "decembar": 12,
}
LOZ_DATE = re.compile(
    r"(\d{1,2})\.\s*(januar|februar|mart|april|maj|jun|jul|avgust|"
    r"septembar|oktobar|novembar|decembar)\s+(20\d{2})\."
    r"(?:\s*@\s*(\d{1,2}):(\d{2}))?", re.I
)
RU_DATE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})\.(20\d{2})(?!\d)")


def trusted_url(base: str, link: str, prefix: str) -> str:
    if not isinstance(link, str):
        return ""
    try:
        p = urlparse(urljoin(base, link))
    except ValueError:
        return ""
    expected = urlparse(base)
    if (p.scheme != "https" or p.hostname not in
        (expected.hostname, "www." + expected.hostname)
        or p.username or p.password or not p.path.startswith(prefix)
        or p.path.rstrip("/") == prefix.rstrip("/")):
        return ""
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") + "/", "", "", ""))


def loz_links(markup: str) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    found = []
    for a in soup.select("a[href]"):
        link = trusted_url(LOZ, a.get("href", ""), "/pojedinacni-dogadjaj/")
        if link and link not in found:
            found.append(link)
    return found[:30]


def loz_detail(markup: str, url: str, now: datetime):
    from afisha_bot import Event, TZ, clean, event_in_window, safe_ticket_url
    source = trusted_url(LOZ, url, "/pojedinacni-dogadjaj/")
    if not source:
        return None
    soup = BeautifulSoup(markup, "html.parser")
    # Ložionica has menu h2 headings ("Program", "Bukiraj prostor")
    # before the actual event h2. Use per-page OpenGraph title to identify
    # the event heading, rather than blindly taking the first h1/h2.
    og = soup.select_one("meta[property='og:title']")
    og_title = clean(og.get("content", "").split(" | ")[0] if og else "", 125)
    heading = next((
        h for h in soup.select("h1,h2,h3")
        if og_title and clean(h.get_text(" ", strip=True), 125).casefold() == og_title.casefold()
    ), None)
    if heading is None:
        heading = soup.select_one(".tribe-events-single-event-title")
    if heading is None and not og_title:
        # Minimal verified pages without OpenGraph metadata.
        heading = soup.select_one("h1,h2")
    title = og_title or clean(heading.get_text(" ", strip=True) if heading else "", 125)
    if not title:
        return None
    # The Ložionica Elementor templates may render the date in heading-like
    # divs, not a tribe-events-schedule element. Search near the event title.
    header = soup.select_one(".tribe-events-schedule")
    raw = (header.get_text(" ", strip=True) if header else "")[:1000]
    matches = list(LOZ_DATE.finditer(raw))
    if not matches:
        # The exact event title occurs in main content; the first 4K chars
        # after it contain the event start/end, but exclude global navigation.
        scope = soup.select_one("main") or soup.select_one("article") or soup
        all_text = " ".join(scope.stripped_strings)
        match_title = re.search(re.escape(title), all_text, re.I)
        tail = all_text[match_title.end():match_title.end()+3500] if match_title else all_text
        matches = list(LOZ_DATE.finditer(tail))
    if not matches:
        return None

    def to_datetime(m):
        return datetime(int(m.group(3)), MONTHS[m.group(2).casefold()],
                        int(m.group(1)), int(m.group(4) or 0),
                        int(m.group(5) or 0), tzinfo=TZ)
    try:
        start = to_datetime(matches[0])
        end = to_datetime(matches[1]) if len(matches) > 1 else None
    except (ValueError, KeyError):
        return None
    if end and end < start:
        end = None

    # A brief factual excerpt for the editorial model, not a reproduced article.
    content = (soup.select_one(".tribe-events-single-event-description")
               or soup.select_one("article") or soup.select_one("main"))
    pieces = [
        clean(p.get_text(" ", strip=True), 310)
        for p in content.select("p")[:4]
    ] if content else []
    description = " ".join(p for p in pieces if len(p) >= 25)[:415]
    if len(description) < 50:
        # Elementor may contain the event synopsis in a prose div.
        body = (soup.select_one(".elementor-widget-theme-post-content")
                or soup.select_one("main") or soup)
        if body:
            blocks = [
                clean(div.get_text(" ", strip=True), 400)
                for div in body.select(".elementor-widget-text-editor")[:5]
            ]
            description = " ".join(t for t in blocks if len(t) >= 60)[:415]
    if len(description) < 50:
        # Live Ložionica Elementor event pages keep the synopsis as loose
        # text between the first event date range and the "DATUM I VREME"
        # detail panel, not in a <p>/article/main/widget-text-editor.
        full = " ".join(soup.stripped_strings)
        first = LOZ_DATE.search(full)
        if first:
            tail = full[first.end():]
            second = LOZ_DATE.search(tail)
            if second and second.start() < 100:
                tail = tail[second.end():]
            # Strip heading labels; stop before ticket/location boilerplate.
            section = re.split(
                r"DATUM I VREME|Датум и време|KATEGORIJA|Категорије",
                tail, maxsplit=1, flags=re.IGNORECASE,
            )[0]
            section = re.sub(
                r"^(?:\s*[-–]\s*\d{1,2}:\d{2}\s*|\s*(?:Kupi kartu|Prijavi se!?|Image)\s*)+",
                "", section, flags=re.IGNORECASE,
            )
            description = clean(section, 415)
    if len(description) < 50:
        return None
    text = clean(" ".join(soup.stripped_strings), 3200)
    price = "не указана"
    # Pricing is displayed in the event's specific "CENA" metadata.
    metadata = soup.select_one(".tribe-events-event-meta") or soup
    meta_text = clean(metadata.get_text(" ", strip=True), 2300)
    price_match = re.search(r"(?:\bCENA\b|ЦЕНА)[\s\S]{0,90}?(?:RSD\s*(\d[\d.]*)(?!\d)|(\d[\d.]*)\s*RSD)", meta_text, re.I)
    if not price_match:
        price_match = re.search(r"(?<!\w)(?:RSD\s*(\d[\d.]*)(?!\d)|(\d[\d.]*)\s*RSD)", text, re.I)
    if price_match:
        numeric = (price_match.group(1) or price_match.group(2)).replace(".", "")
        if numeric.isdigit() and 100 <= int(numeric) <= 100_000:
            price = numeric + " дин."
    if re.search(r"(?:ulaz slobodan|besplatan ulaz|besplatno)", meta_text, re.I):
        price = "бесплатно (по данным площадки)"

    catnode = soup.select_one(".tribe-events-event-categories")
    cat = clean(catnode.get_text(" ", strip=True), 100) if catnode else ""
    if not cat:
        # The live Elementor page's category is in a dedicated section:
        # "Категорије: Radionica CENA" or "Категорије: VR izložba CENA".
        cat_full = clean(" ".join(soup.stripped_strings), 9000)
        category_match = re.search(
            r"(?:Категорије\s*:|KATEGORIJA\s*:?)\s*(.*?)\s+(?:CENA|ЦЕНА|KARTE)",
            cat_full, re.I,
        )
        if category_match:
            cat = clean(category_match.group(1), 100)
    joined = (title + " " + cat + " " + description[:100]).casefold()
    # Trust the event's explicit category over incidental words such as
    # "izložba" in the description of a workshop related to an exhibition.
    category_label = cat.casefold().strip()
    if any(w in category_label for w in ("radionic", "workshop")):
        category = "Workshop"
    elif any(w in category_label for w in ("pozoriš", "pozoris", "predstav", "theatre")):
        category = "Theatre"
    elif any(w in category_label for w in ("izložb", "izlozb", "exhibit")):
        category = "Exhibition"
    elif any(w in category_label for w in ("koncert", "dj nastup", "music")):
        category = "Concert"
    else:
        category = (
            "Workshop" if any(w in joined for w in ("radionic", "workshop", "pop-up"))
            else "Exhibition" if any(w in joined for w in ("izložb", "izlozb", "imerziv"))
            else "Theatre" if any(w in joined for w in ("pozoriš", "pozoris", "predstav", "theatre"))
            else "Concert" if any(w in joined for w in ("koncert", "fourchestra", "muzika", "dj nastup"))
            else "Other"
        )
    if category == "Other":
        return None

    ticket = ""
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True)
        if re.search(r"kupi kartu|kupi ulaznic|tickets?|buy tickets", label, re.I):
            link = safe_ticket_url(urljoin(source, anchor.get("href", "")), source)
            if urlparse(link).hostname in ("efinity.rs", "www.efinity.rs", "tickets.rs", "www.tickets.rs"):
                ticket = link
                break

    # Prefer a title-matched official poster (including lazy-loaded images);
    # meta previews are considered only after event-specific imagery.
    image = find_official_event_poster(soup, source, title)
    ev = Event(url=source, title=title, city="Белград", venue="Ložionica, Ulica Ideja 2",
               start=start, end=end, description=description, category=category,
               image=image, price=price, ticket_url=ticket)
    return ev if event_in_window(ev, now) else None


def afisha_url(href: str) -> str:
    try:
        u = urlparse(urljoin(AFISHA, href or ""))
    except ValueError:
        return ""
    if u.scheme != "https" or u.hostname not in ("afisha.rs", "www.afisha.rs") or u.username or u.password:
        return ""
    segments = [s for s in u.path.split("/") if s]
    if len(segments) < 3 or segments[0] != "ru" or len(segments[-1]) < 12:
        return ""
    if "/" + "/".join(segments[:2]) not in AFISHA_CATEGORIES:
        return ""
    return urlunparse((u.scheme, u.netloc, u.path.rstrip("/"), "", "", ""))


def afisha_cards(markup: str, now: datetime, category: str) -> list:
    """Factual listing-only extraction: strict date and venue, no copied prose."""
    from afisha_bot import Event, TZ, clean, event_in_window
    soup = BeautifulSoup(markup, "html.parser")
    result = []
    for link in soup.select("a[href]"):
        url = afisha_url(link.get("href", ""))
        if not url or ("/" + "/".join(urlparse(url).path.split("/")[1:3])) != category:
            continue
        title = clean(link.get_text(" ", strip=True), 160)
        if len(title) < 12 or len(title) > 140:
            continue
        # Match a date in the same small list item, not a date elsewhere
        # on the page. Each card is a source-attributed factual record.
        node = link.parent
        date_match = None
        for _ in range(3):
            if node is None:
                break
            text = clean(node.get_text(" ", strip=True), 460)
            if len(text) > 450:
                break
            date_match = RU_DATE.search(text)
            if date_match:
                break
            node = node.parent
        if not date_match:
            continue
        try:
            start = datetime(int(date_match.group(3)), int(date_match.group(2)),
                             int(date_match.group(1)), tzinfo=TZ)
        except ValueError:
            continue
        # Avoid guessing an event venue from neighboring cards.
        local_anchors = node.select("a[href]")
        named_places = [
            clean(a.get_text(" ", strip=True), 90) for a in local_anchors
            if a is not link and clean(a.get_text(" ", strip=True), 90)
            and a.get("href", "").startswith("/ru/venues/")
        ]
        venue = named_places[0] if named_places else ""
        if not venue:
            continue
        cat = (
            "Workshop" if "master" in category else
            "Theatre" if "teatr" in category else
            "Exhibition" if "vystav" in category else
            "Family" if "deti" in category else
            "Concert" if "koncerty" in category else
            "Cinema" if "filmy" in category else "Lecture"
        )
        # The editor receives only a short original factual summary.
        ev = Event(url=url, title=title, city="Белград", venue=venue, start=start,
                   description=f"{title}. Мероприятие в {venue}, Белград.",
                   category=cat, price="не указана")
        if event_in_window(ev, now) and all(x.key != ev.key for x in result):
            result.append(ev)
    return result[:12]



KCGRAD = "https://www.kcgrad.rs"
KCGRAD_CALENDAR = KCGRAD + "/calendar/"
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
KC_DAY = re.compile(
    r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),"
    r"\s*(\d{1,2})(?:st|nd|rd|th)\s+([a-z]+)$", re.I
)
KC_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*[–—-]\s*(.{11,})$")


def kcgrad_cards(markup: str, now: datetime) -> list:
    """Read dated official calendar entries, not arbitrary article snippets.

    Each item is an actual performance at the venue, not a scraped ticket link.
    Simple recurring classes and past dates are excluded.
    """
    from afisha_bot import Event, TZ, clean, event_in_window
    soup = BeautifulSoup(markup, "html.parser")
    active_day = None
    events = []
    for line in soup.stripped_strings:
        value = clean(line, 350)
        heading = KC_DAY.fullmatch(value)
        if heading:
            try:
                month = EN_MONTHS[heading.group(2).lower()]
                day = int(heading.group(1))
                active_day = datetime(now.year, month, day, tzinfo=TZ)
            except (KeyError, ValueError):
                active_day = None
            continue
        if not active_day:
            continue
        if value.startswith("If you need any additional information"):
            break
        match = KC_TIME.fullmatch(value)
        if not match:
            continue
        title = clean(match.group(3), 125)
        if len(title) < 10 or any(
            x in title.casefold() for x in
            ("language café", "language cafe", "regular lessons")
        ):
            continue
        try:
            start = active_day.replace(hour=int(match.group(1)), minute=int(match.group(2)))
        except ValueError:
            continue
        label = title.casefold()
        category = (
            "Exhibition" if "exhibition" in label
            else "Concert" if any(x in label for x in ("concert", "dj set", "live", "theme party"))
            else "Theatre" if any(x in label for x in ("drag show", "performance", "predstava"))
            else "Workshop" if any(x in label for x in ("pop-up", "deli monday", "brunch", "predstavljanje"))
            else "Other"
        )
        if category == "Other":
            continue
        event = Event(
            url=KCGRAD_CALENDAR, title=title, city="Белград",
            venue="KC Grad, Braće Krsmanović 4",
            start=start, category=category, price="не указана",
            description=f"{title}. Официальная программа KC Grad: начало в {start:%H:%M}.",
        )
        if event_in_window(event, now) and all(x.key != event.key for x in events):
            events.append(event)
    return events[:24]


def robots_allowed(session: requests.Session, origin: str, urls: list[str], ua: str):
    """No permissions inference or scraper bypass when robots are unavailable."""
    try:
        result = session.get(origin + "/robots.txt", timeout=12)
        result.raise_for_status()
        rules = RobotFileParser()
        rules.parse(result.text.splitlines())
        return [url for url in urls if rules.can_fetch(ua, url)]
    except (requests.RequestException, ValueError):
        return []


def collect_local_culture(session: requests.Session, now: datetime) -> list:
    from afisha_bot import UA
    gathered = []
    if os.getenv("AFISHA_ENABLE_LOZIONICA", "1") == "1":
        if robots_allowed(session, LOZ, [LOZ_CALENDAR], UA):
            try:
                index = session.get(LOZ_CALENDAR, timeout=16)
                index.raise_for_status()
                links = loz_links(index.text) if len(index.content) < 1_800_000 else []
                allowed = robots_allowed(session, LOZ, links, UA) if links else []
                for url in allowed[:16]:
                    try:
                        page = session.get(url, timeout=14)
                        page.raise_for_status()
                        if len(page.content) <= 1_800_000:
                            e = loz_detail(page.text, url, now)
                            if e:
                                gathered.append(e)
                    except requests.RequestException:
                        continue
                print(f"Ložionica: {len(gathered)} upcoming or ongoing cultural events.")
            except requests.RequestException:
                print("Ložionica official culture calendar unavailable.")
    if os.getenv("AFISHA_ENABLE_LOCAL_LISTINGS", "0") == "1":
        allowed = robots_allowed(session, AFISHA,
                                 [AFISHA + path for path in AFISHA_CATEGORIES], UA)
        for url in allowed[:6]:
            try:
                page = session.get(url, timeout=13)
                page.raise_for_status()
                if len(page.content) <= 1_800_000:
                    cards = afisha_cards(page.text, now, urlparse(url).path)
                    gathered.extend(cards)
                    print(f"Local listing {urlparse(url).path}: {len(cards)} cultural events.")
            except requests.RequestException:
                continue
    if os.getenv("AFISHA_ENABLE_KCGRAD", "1") == "1":
        if robots_allowed(session, KCGRAD, [KCGRAD_CALENDAR], UA):
            try:
                page = session.get(KCGRAD_CALENDAR, timeout=16)
                page.raise_for_status()
                if len(page.content) <= 1_800_000:
                    cards = kcgrad_cards(page.text, now)
                    gathered.extend(cards)
                    print(f"KC Grad official calendar: {len(cards)} cultural events.")
            except requests.RequestException:
                print("KC Grad official event calendar unavailable.")
    return gathered
