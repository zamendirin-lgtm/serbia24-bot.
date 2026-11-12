"""Serbia 24 real estate: conservative discovery and Telegram publishing.

Reads public, permitted listing pages (facts and canonical links only, no copied photos).
Not an estate agency or a guarantee of listing status/price/legal title.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://www.4zida.rs"
STATE = Path("data/estate_seen.json")
UA = "Serbia24PropertyFinder/1.0 (+https://t.me/Serbia24Dom)"
TZ = ZoneInfo("Europe/Belgrade")
CITIES = {
    "beograd": "Белград",
    "novi-sad": "Нови-Сад",
    "nis": "Ниш",
    "pancevo": "Панчево",
    "zrenjanin": "Зренянин",
    "subotica": "Суботица",
    "kragujevac": "Крагуевац",
}
# Different city/types are rotated throughout the day to reduce request volume.
KINDS = {
    "prodaja-stanova": ("Продажа", "квартиры"),
    "izdavanje-stanova": ("Аренда", "квартиры"),
    "prodaja-kuca": ("Продажа", "дома"),
}
AD_ID = re.compile(r"/[0-9a-f]{24}$", re.I)
MONEY = re.compile(r"(\d[\d.,\s]{0,12})\s*€")
AREA = re.compile(r"(\d{1,3}(?:[,.]\d{1,2})?)\s*m(?:²|2)\b", re.I)
DATE = re.compile(r"(?:Oglas\s+ažuriran|Ažurirano)\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
UNAVAILABLE = ("oglas nije aktivan", "oglas nije dostupan", "oglas je uklonjen")


@dataclass(frozen=True)
class Offer:
    url: str
    city: str
    kind: str
    title: str
    price_eur: int
    area_m2: float
    updated: str
    advertiser: str = "Не указан"

    @property
    def unit_price(self) -> float:
        return self.price_eur / self.area_m2

    @property
    def key(self) -> str:
        return hashlib.sha256(self.url.encode("utf8")).hexdigest()


def canonical_url(raw: str) -> str:
    url = urlparse(urljoin(BASE, raw))
    if url.scheme != "https" or url.hostname not in ("www.4zida.rs", "4zida.rs"):
        return ""
    return urlunparse(("https", "www.4zida.rs", url.path.rstrip("/"), "", "", ""))


def listing_links(markup: str, kind: str, limit: int = 12) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    links = []
    seen = set()
    for node in soup.select("a[href]"):
        url = canonical_url(node["href"])
        path = urlparse(url).path
        if not path.startswith("/" + kind + "/") or not AD_ID.search(path):
            continue
        if url not in seen:
            links.append(url)
            seen.add(url)
        if len(links) >= limit:
            break
    return links


def _numeric_price(raw: str) -> int:
    # Serbian listing prices use "." as a thousands separator.
    return int(re.sub(r"[^\d]", "", raw))


def parse_offer(markup: str, url: str, city: str, kind: str, now: datetime | None = None) -> Offer | None:
    soup = BeautifulSoup(markup, "html.parser")
    headline = soup.find("h1")
    if headline is None:
        return None
    title = headline.get_text(" ", strip=True)
    raw_text = soup.get_text(" ", strip=True)
    if any(flag in raw_text.lower() for flag in UNAVAILABLE):
        return None
    amount = MONEY.search(title)
    area = AREA.search(title)
    stamp = DATE.search(raw_text)
    if not (amount and area and stamp):
        return None
    try:
        price = _numeric_price(amount.group(1))
        size = float(area.group(1).replace(",", "."))
        updated = datetime.strptime(stamp.group(1), "%d.%m.%Y").date()
    except (ValueError, OverflowError):
        return None
    today = (now or datetime.now(TZ)).date()
    if updated > today + timedelta(days=1) or updated < today - timedelta(days=14):
        return None
    if not (18 <= size <= 450):
        return None
    if kind.startswith("izdavanje-") and not (70 <= price <= 3500):
        return None
    if kind.startswith("prodaja-") and not (15000 <= price <= 700000):
        return None

    # Only classify the advertiser using the contact section, not global navigation.
    contact = raw_text.split("Kontakt oglašivača", 1)
    seller = "Не указан"
    if len(contact) == 2:
        contact_text = contact[1][:280].lower()
        if re.search(r"\b(?:agencija|agent|trgovac)\b", contact_text):
            seller = "Агентство / посредник"
        elif re.search(r"\b(?:vlasnik|fizičko lice)\b", contact_text):
            seller = "Собственник (по объявлению)"
    return Offer(
        url=canonical_url(url),
        city=CITIES[city],
        kind=kind,
        title=title[:120],
        price_eur=price,
        area_m2=size,
        updated=updated.isoformat(),
        advertiser=seller,
    )


def allowed(robots: RobotFileParser, url: str) -> bool:
    return bool(robots.can_fetch(UA, url))


def robots_rules(session: requests.Session) -> RobotFileParser:
    response = session.get(BASE + "/robots.txt", timeout=12)
    response.raise_for_status()
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser


def pick_cities(now: datetime) -> list[str]:
    names = list(CITIES)
    # Two cities per run, rotating hourly; all cities visited every 4 hours.
    offset = ((now.toordinal() * 24 + now.hour) * 2) % len(names)
    return [names[offset], names[(offset + 1) % len(names)]]


def scan(session: requests.Session, now: datetime) -> list[Offer]:
    try:
        rules = robots_rules(session)
    except requests.RequestException as exc:
        print(f"Unable to check robots.txt: {exc}; skipping scans.")
        return []
    results = []
    for city in pick_cities(now):
        for kind in KINDS:
            search_url = f"{BASE}/{kind}/{city}"
            if not allowed(rules, search_url):
                continue
            try:
                page = session.get(search_url, timeout=15)
                page.raise_for_status()
            except requests.RequestException as exc:
                print(f"Search unavailable: {city}/{kind}: {type(exc).__name__}")
                continue
            for link in listing_links(page.text, kind, limit=8):
                if not allowed(rules, link):
                    continue
                try:
                    detail = session.get(link, timeout=12)
                    detail.raise_for_status()
                    offer = parse_offer(detail.text, link, city, kind, now)
                except requests.RequestException:
                    continue
                if offer is not None:
                    results.append(offer)
                time.sleep(0.2)
            time.sleep(0.4)
    unique = {}
    for offer in results:
        unique[offer.url] = offer
    return list(unique.values())


def price_cap(offer: Offer) -> int:
    is_bg = offer.city == "Белград"
    if offer.kind == "izdavanje-stanova":
        return 600 if is_bg else 440
    if offer.kind == "prodaja-kuca":
        return 165000 if is_bg else 115000
    return 150000 if is_bg else 110000


def shortlist(offers: list[Offer], seen: dict, limit: int = 1) -> list[Offer]:
    groups: dict[tuple[str, str], list[float]] = {}
    for offer in offers:
        groups.setdefault((offer.city, offer.kind), []).append(offer.unit_price)
    qualified: list[tuple[float, Offer]] = []
    for offer in offers:
        if offer.key in seen or offer.price_eur > price_cap(offer):
            continue
        comparable = groups[(offer.city, offer.kind)]
        med = statistics.median(comparable) if len(comparable) >= 4 else None
        relative = (offer.unit_price / med) if med else None
        # Avoid outlier bait. A low price alone is not proof of a good deal.
        if relative is not None and relative < 0.40:
            continue
        # Require below local sample median, or an especially low absolute price.
        within_budget = offer.price_eur <= price_cap(offer) * 0.78
        if not within_budget and (relative is None or relative > 0.90):
            continue
        price_index = offer.price_eur / price_cap(offer)
        score = (relative if relative is not None else 1.0) * 0.7 + price_index * 0.3
        if offer.advertiser.startswith("Собственник"):
            score -= 0.06
        qualified.append((score, offer))
    return [offer for _, offer in sorted(qualified, key=lambda x: x[0])[:limit]]


def format_post(offer: Offer, now: datetime) -> str:
    intent, subject = KINDS[offer.kind]
    detail = "€/м²/мес." if intent == "Аренда" else "€/м²"
    amount = f"{offer.price_eur:,}".replace(",", " ")
    unit = f"{offer.unit_price:,.0f}".replace(",", " ")
    period = "/мес." if intent == "Аренда" else ""
    title = html.escape(offer.title)
    url = html.escape(offer.url, quote=True)
    checked = now.strftime("%d.%m.%Y %H:%M")
    return (
        f"🏠 <b>{intent}: {subject} · {offer.city}</b>\n"
        f"💶 <b>{amount} €{period}</b> · 📐 {offer.area_m2:g} м² ({unit} {detail})\n"
        f"📍 {title}\n"
        f"👤 {html.escape(offer.advertiser)}\n"
        f"🗓 Объявление обновлено: {offer.updated}; проверено: {checked} (Белград)\n"
        f"🔎 <i>Предварительный отбор по цене. Доступность и документы не подтверждены.</i>\n"
        f'🔗 <a href="{url}">Объявление и контакты</a>\n'
        f"⚠️ Не переводите задаток до проверки объекта и условий."
    )


def send_telegram(session: requests.Session, token: str, chat_id: str, post: str) -> bool:
    response = session.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": post,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=18,
    )
    if not response.ok:
        # Do not include the sensitive request URL containing the bot token in logs.
        print(f"Telegram returned HTTP {response.status_code}; check group ID and admin permissions.")
        return False
    return response.json().get("ok", False) is True


def load_seen() -> dict:
    try:
        result = json.loads(STATE.read_text(encoding="utf8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def main() -> int:
    now = datetime.now(TZ)
    if not (8 <= now.hour < 22) and os.getenv("ESTATE_ALLOW_NIGHT", "") != "1":
        print("Quiet hours 22:00-08:00 Belgrade.")
        return 0
    token = os.getenv("PROPERTY_BOT_TOKEN", "").strip()
    chat_id = os.getenv("PROPERTY_CHAT_ID", "").strip()
    dry = os.getenv("PROPERTY_DRY_RUN", "") == "1"
    if not dry and not (token and chat_id):
        print("PROPERTY_BOT_TOKEN/PROPERTY_CHAT_ID missing; no posts.")
        return 0
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "sr-RS,sr;q=0.9"})
    offers = scan(session, now)
    print(f"Public source candidates parsed: {len(offers)}")
    seen = load_seen()
    picks = shortlist(offers, seen, limit=1)
    for offer in picks:
        post = format_post(offer, now)
        if dry:
            print(post)
            continue
        if send_telegram(session, token, chat_id, post):
            seen[offer.key] = {
                "url": offer.url,
                "price": offer.price_eur,
                "posted_at": now.isoformat(),
            }
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(
                json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
            )
            print("Published a listing link successfully.")
        else:
            print("No state update after Telegram failure.", file=sys.stderr)
            return 1
    if not picks:
        print("No sufficiently interesting and fresh listings this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
