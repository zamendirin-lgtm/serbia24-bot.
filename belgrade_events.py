"""Discover public Belgrade events from RUN BGD's public city calendar.

We read short factual calendar fields, not their photos or full articles. An
explicit 'Tickets' link on the same event card is the only purchase URL.
robots.txt is respected and any source failure is non-fatal.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.runbgd.com"
CALENDAR = BASE + "/whats-on"
MAX_EVENTS = 60
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
DATE = re.compile(r"(?<!\w)(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{4})(?!\d)", re.I)


def source_url(raw: str) -> str:
    url = urlparse(urljoin(CALENDAR, raw or ""))
    if url.scheme != "https" or url.hostname not in ("runbgd.com", "www.runbgd.com"):
        return ""
    if not url.path.startswith("/whats-on/") or url.username or url.password:
        return ""
    return urlunparse((url.scheme, url.netloc, url.path.rstrip("/"), "", "", ""))


def _field(article, token: str):
    # Avoid CSS module hash suffixes: '_where_3unba_95', '_price_3unba_82'
    return article.select_one('[class*="_' + token + '_"]')


def _plain(node) -> str:
    if not node:
        return ""
    return " ".join(node.stripped_strings)


def parse_belgrade_cards(markup: str, now: datetime) -> list:
    from afisha_bot import Event, TZ, safe_ticket_url, event_in_window, clean

    soup = BeautifulSoup(markup, "html.parser")
    found = []
    already = set()
    # 'Upcoming' only; avoid cards rendered under 'Past'
    heading = next((h for h in soup.select("h2")
                    if h.get_text(" ", strip=True).casefold() == "upcoming"), None)
    if not heading:
        return []
    section = heading.find_parent("section")
    if not section:
        return []
    for article in section.select('article[data-event]')[:MAX_EVENTS]:
        a = article.select_one('h3 a[href]')
        if not a:
            continue
        url = source_url(a.get("href", ""))
        title = clean(a.get_text(" ", strip=True), 140)
        if not url or not title:
            continue
        date_field = _field(article, "when")
        text = _plain(date_field).upper() if date_field else ""
        match = DATE.search(text)
        if not match:
            continue
        try:
            d = date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
        except (ValueError, KeyError):
            continue
        start = datetime(d.year, d.month, d.day, tzinfo=TZ)
        venue_node = _field(article, "where")
        if venue_node:
            venue_node = BeautifulSoup(str(venue_node), "html.parser")
            for part in venue_node.select('[class*="_range_"]'):
                part.decompose()
        venue = clean(_plain(venue_node), 90)
        description = clean(_plain(_field(article, "desc")), 420)
        category = clean(_plain(_field(article, "category")), 50)
        price_source = clean(_plain(_field(article, "price")), 50)
        # No price in card does not imply a free event.
        price = "не указана"
        m = re.fullmatch(r"(\d[\d., ]{0,8})\s*(?:RSD|DIN|DINARA)", price_source, re.I)
        if m:
            # Aggregator cards may show a discounted / lowest ticket category.
            # Never present the card's number as the universal adult price.
            price = "от " + m.group(1).strip() + " дин. (по данным афиши)"
        elif re.fullmatch(r"(?:FREE|BESPLATNO|ULAZ SLOBODAN)", price_source, re.I):
            price = "Бесплатно (по данным источника)"
        if (
            "muzej savremene umetnosti" in venue.casefold()
            and "prekretnice ka modernosti" in title.casefold()
            and m is not None and m.group(1).strip() == "300"
        ):
            # Museum's own visitor tariff (msub.org.rs/poseta/) checked 2026-11-13:
            # standard 600 RSD; reduced 300 RSD. RUN BGD lists only the minimum.
            price = "обычный — 600 дин., льготный — 300 дин."
        tickets = ""
        for el in article.select('a[href]'):
            if not re.search(r"\b(?:tickets?|buy\s+tickets?|karte|ulaznice)\b",
                             _plain(el), re.I):
                continue
            raw = urljoin(CALENDAR, el.get("href", ""))
            checked = safe_ticket_url(raw, url)
            if checked:
                tickets = checked
                break
        event = Event(
            url=url, title=title, city="Белград", venue=venue,
            start=start, description=description, category=category,
            price=price, ticket_url=tickets,
            # No photo redistribution rights established for this provider.
            image="",
        )
        if event_in_window(event, now) and url not in already:
            found.append(event)
            already.add(url)
    return found


def collect_belgrade_events(session: requests.Session, now: datetime) -> list:
    from afisha_bot import UA

    if os.getenv("AFISHA_ENABLE_BELGRADE", "1") != "1":
        return []
    try:
        robots = session.get(BASE + "/robots.txt", timeout=12)
        if not robots.ok:
            print("Belgrade robots.txt unavailable. Skipping.")
            return []
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        if not parser.can_fetch(UA, CALENDAR):
            print("Belgrade source disallows automated access. Skipping.")
            return []
        response = session.get(CALENDAR, timeout=19)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            print("Belgrade calendar unexpectedly large. Skipping.")
            return []
        response.encoding = response.apparent_encoding if not response.encoding or response.encoding.lower() == "iso-8859-1" else response.encoding
        events = parse_belgrade_cards(response.text, now)
        print(f"Belgrade city calendar: {len(events)} upcoming events parsed.")
        return events
    except requests.RequestException:
        print("Belgrade source temporarily unavailable.")
        return []
