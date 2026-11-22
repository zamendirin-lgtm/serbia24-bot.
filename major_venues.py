"""Official major venues: Belgrade Arena and Serbian National Theatre, Novi Sad.

Read short factual event data; no invented prices, sports or unrelated media.
Obey source robots.txt and require dated event detail / ticket records.
"""
import json
import os
import re
from datetime import datetime
from urllib.parse import urlparse, urljoin, urlunparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from afisha_media import find_official_event_poster

ARENA = "https://arenabeograd.com"
SNP = "https://prodaja.snp.org.rs"
ARENA_LIST = ARENA + "/"
SNP_LIST = SNP + "/rs/site/index"
ISO = re.compile(r"(?<!\d)(20\d{2}-\d\d-\d\d)(?:[T ](\d\d?:\d\d))?")
MONTHS = dict(januar=1, februar=2, mart=3, april=4, maj=5, jun=6, jul=7,
              avgust=8, septembar=9, oktobar=10, novembar=11, decembar=12)
SNP_DATE = re.compile(
    r"\b(\d{1,2})\.\s*([a-zčćšđž]+)\s+(20\d\d)\.\s*u\s*(\d\d?):(\d\d)", re.I
)


def arena_url(value):
    p = urlparse(urljoin(ARENA, value or ""))
    if (p.scheme != "https" or p.hostname not in ("arenabeograd.com", "www.arenabeograd.com")
            or p.username or p.password or not p.path.startswith("/dogadjaj/")
            or p.path.rstrip("/") == "/dogadjaj"):
        return ""
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") + "/", "", "", ""))


def arena_links(markup):
    soup = BeautifulSoup(markup, "html.parser")
    result = []
    for a in soup.select("a[href]"):
        u = arena_url(a.get("href", ""))
        if u and u not in result:
            result.append(u)
    return result[:35]


def _arena_start(soup):
    from afisha_bot import parse_date
    selectors = (".tribe-events-schedule abbr, "
                 ".tribe-events-meta-group-details abbr, "
                 ".tribe-events-event-meta abbr, [itemprop='startDate'], "
                 "time[datetime], abbr[title]")
    for node in soup.select(selectors)[:30]:
        for value in (node.get("title"), node.get("datetime"), node.get("content"),
                      node.get_text(" ", strip=True)):
            m = ISO.search(value or "")
            if m:
                return parse_date(m.group(1) + ("T" + m.group(2) if m.group(2) else ""))
    details = soup.select_one(".tribe-events-event-meta")
    m = ISO.search(str(details)[:3500]) if details else None
    return parse_date(m.group(1) + ("T" + m.group(2) if m.group(2) else "")) if m else None


def arena_detail(markup, url, now):
    from afisha_bot import Event, clean, event_in_window, is_routine_sports_fixture, safe_ticket_url
    source = arena_url(url)
    if not source:
        return None
    soup = BeautifulSoup(markup, "html.parser")
    h = soup.select_one("h1.tribe-events-single-event-title") or soup.select_one("h1")
    title = clean(h.get_text(" ", strip=True) if h else "", 130)
    if not title or re.search(r"(?i)euroleague|vs\.?|utakmica|super enduro|bkfc|mma|fudbal", title):
        return None
    date = _arena_start(soup)
    if not date:
        return None
    tags = " ".join(x.get_text(" ", strip=True) for x in soup.select(
        ".tribe-events-event-categories a, a[href*='/category/']"
    ))
    body = soup.select_one(".tribe-events-single-event-description") or soup.select_one("main") or soup
    description = clean(" ".join(x.get_text(" ", strip=True) for x in body.select("p")[:4]), 500)
    if not re.search("koncert|concert|muzik|music|balet|ballet|predstav|opera|show|šou", title+" "+tags+" "+description, re.I):
        return None
    if re.search("sport|utakmica|basketball|fudbal", tags, re.I):
        return None
    image = find_official_event_poster(soup, source, title)
    ticket = ""
    for a in body.select("a[href]"):
        if not re.search("ulaznic|karte|tickets|kupi", a.get_text(" ", strip=True), re.I):
            continue
        u = safe_ticket_url(urljoin(source, a.get("href", "")), source)
        p = urlparse(u)
        if p.hostname in ("tickets.rs", "www.tickets.rs", "efinity.rs", "www.efinity.rs") and (
                "/event/" in p.path or "/tour/" in p.path):
            ticket = u
            break
    cat = "Ballet" if re.search("balet|ballet", title+" "+tags, re.I) else "Concert"
    event = Event(source, title, "Белград", "Белградская арена (Beogradska arena)",
                  date, description=description, category=cat, image=image,
                  price="не указана", ticket_url=ticket)
    return event if event_in_window(event, now) and not is_routine_sports_fixture(event) else None


def snp_url(value):
    p = urlparse(urljoin(SNP, value or ""))
    if (p.scheme != "https" or p.hostname != "prodaja.snp.org.rs" or
            p.username or p.password or not re.fullmatch(
                r"/(?:rs|sr)/site/eventDetail/index/\d+", p.path)):
        return ""
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def snp_cards(markup, now):
    from afisha_bot import Event, TZ, clean, event_in_window
    soup = BeautifulSoup(markup, "html.parser")
    found = []
    for a in soup.select("h3 a[href], h4 a[href]"):
        url = snp_url(a.get("href", ""))
        if not url:
            continue
        title = clean(a.get_text(" ", strip=True), 130)
        ancestor, match, txt = a.parent, None, ""
        for _ in range(6):
            if not ancestor:
                break
            txt = ancestor.get_text(" ", strip=True)[:1200]
            match = SNP_DATE.search(txt)
            if match:
                break
            ancestor = ancestor.parent
        if not match:
            continue
        month = MONTHS.get(match.group(2).lower())
        if not month:
            continue
        try:
            start = datetime(int(match.group(3)), month, int(match.group(1)),
                             int(match.group(4)), int(match.group(5)), tzinfo=TZ)
        except ValueError:
            continue
        price = "не указана"
        # Ticket pages expose ranges (600,00 - 1.000,00 RSD). Show the
        # lowest category and explicitly call it an "от" price.
        price_range = re.search(
            r"(\d[\d.]*(?:,\d{2})?)\s*[-–]\s*(\d[\d.]*(?:,\d{2})?)\s*RSD",
            txt, re.I,
        )
        single = re.search(r"(\d[\d.]*(?:,\d{2})?)\s*RSD", txt, re.I)
        m = price_range or single
        if m:
            amount = m.group(1).split(",")[0].replace(".", "")
            if amount.isdigit():
                price = "от " + amount + " дин. (по данным кассы)"
        kind = ("Ballet" if re.search("balet|žizela|жизела", title, re.I) else
                "Opera" if re.search("opera|царска|carska|đani skiki", title+" "+txt, re.I) else "Theatre")
        event = Event(url, title, "Нови-Сад", "Сербский национальный театр",
                      start, description=clean(txt, 350), category=kind, price=price)
        if event_in_window(event, now) and all(e.key != event.key for e in found):
            found.append(event)
    return found[:45]


def _robots(session, base, uri, ua):
    try:
        r = session.get(base + "/robots.txt", timeout=10)
        r.raise_for_status()
        policy = RobotFileParser()
        policy.parse(r.text.splitlines())
        return policy if policy.can_fetch(ua, uri) else None
    except requests.RequestException:
        return None


def collect_major_venues(session, now):
    from afisha_bot import UA
    found = []
    if os.getenv("AFISHA_ENABLE_ARENA", "1") == "1":
        robots = _robots(session, ARENA, ARENA_LIST, UA)
        if robots:
            try:
                index = session.get(ARENA_LIST, timeout=18)
                index.raise_for_status()
                links = arena_links(index.text) if len(index.content) <= 2_000_000 else []
                for url in links:
                    if not robots.can_fetch(UA, url):
                        continue
                    try:
                        page = session.get(url, timeout=14)
                        page.raise_for_status()
                        if len(page.content) <= 2_000_000:
                            e = arena_detail(page.text, url, now)
                            if e:
                                found.append(e)
                    except requests.RequestException:
                        continue
                print(f"Belgrade Arena: {len(found)} future cultural events.")
            except requests.RequestException:
                print("Belgrade Arena official calendar unavailable.")
    if os.getenv("AFISHA_ENABLE_SNP", "1") == "1":
        robots = _robots(session, SNP, SNP_LIST, UA)
        if robots:
            try:
                r = session.get(SNP_LIST, timeout=18)
                r.raise_for_status()
                if len(r.content) <= 2_000_000:
                    snp = snp_cards(r.text, now)
                    found.extend(snp)
                    print(f"Serbian National Theatre: {len(snp)} productions.")
            except requests.RequestException:
                print("Serbian National Theatre ticket calendar unavailable.")
    return found
