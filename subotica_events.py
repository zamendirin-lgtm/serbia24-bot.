"""Official Subotica city tourism calendar: small facts, dates and source links.

Robots-aware, no collection of copyrighted photos. Events in surrounding
villages are labeled as the Subotica area rather than misrepresented as being
within the city itself.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, date
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://visitsubotica.rs"
CALENDAR = BASE + "/manifestacije/"
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d\d)\b")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
CITY_LOCATIONS = ("суботиц", "subotica", "palić", "pali\u0107", "палић", "palić")


def source_url(raw: str) -> str:
    try:
        p = urlparse(raw)
    except ValueError:
        return ""
    if (
        p.scheme != "https" or p.hostname not in ("visitsubotica.rs", "www.visitsubotica.rs")
        or not p.path.startswith("/events/") or p.username or p.password
    ):
        return ""
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


def parse_subotica_cards(markup: str, now: datetime) -> list:
    from afisha_bot import Event, TZ, clean, event_in_window, safe_ticket_url
    soup = BeautifulSoup(markup, "html.parser")
    found, seen = [], set()
    for article in soup.select(".em-event.em-item")[:65]:
        link = article.select_one(".em-item-title a[href]")
        if link is None:
            continue
        url = source_url(link.get("href", ""))
        title = clean(link.get_text(" ", strip=True), 145)
        if not url or not title or url in seen:
            continue
        date_el = article.select_one(".em-event-date")
        date_text = date_el.get_text(" ", strip=True) if date_el else ""
        match = DATE_RE.search(date_text)
        if not match:
            continue
        try:
            d = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            continue
        hour, minute = 0, 0
        time_el = article.select_one(".em-event-time")
        time_match = TIME_RE.search(time_el.get_text(" ", strip=True)) if time_el else None
        if time_match:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23 or minute > 59:
            continue
        start = datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)
        location_el = article.select_one(".em-event-location")
        venue = clean(location_el.get_text(" ", strip=True) if location_el else "", 120)
        description_el = article.select_one(".em-item-desc")
        description = clean(description_el.get_text(" ", strip=True) if description_el else "", 420)
        cats = article.select(".em-event-categories a")
        category = clean(" · ".join(a.get_text(" ", strip=True) for a in cats), 85)
        area_city = "Суботица"
        # Locations such as Ljutovo are outside Subotica proper.
        if venue and not any(term in venue.casefold() for term in CITY_LOCATIONS):
            area_city = "Суботица и окрестности"
        ticket_url = ""
        for a in article.select("a[href]"):
            label = clean(a.get_text(" ", strip=True), 100).casefold()
            if not re.search(r"\b(?:kupite|kupi|karte|ulaznice|tickets?)\b", label, re.I):
                continue
            checked = safe_ticket_url(a.get("href", ""), url)
            if checked:
                ticket_url = checked
                break
        event = Event(
            url=url, title=title, city=area_city, venue=venue, start=start,
            description=description, category=category, price="не указана",
            ticket_url=ticket_url, image="",
        )
        if event_in_window(event, now):
            found.append(event)
            seen.add(url)
    return found


def collect_subotica_events(session: requests.Session, now: datetime) -> list:
    from afisha_bot import UA
    if os.getenv("AFISHA_ENABLE_SUBOTICA", "1") != "1":
        return []
    try:
        robots = session.get(BASE + "/robots.txt", timeout=12)
        if not robots.ok:
            return []
        rp = RobotFileParser()
        rp.parse(robots.text.splitlines())
        if not rp.can_fetch(UA, CALENDAR):
            print("Official Subotica calendar disallows automated reading.")
            return []
        r = session.get(CALENDAR, timeout=20)
        r.raise_for_status()
        if len(r.content) > 2_000_000:
            return []
        r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
        found = parse_subotica_cards(r.text, now)
        print(f"Official Subotica calendar: {len(found)} upcoming events parsed.")
        return found
    except requests.RequestException:
        print("Official Subotica calendar temporarily unavailable.")
        return []
