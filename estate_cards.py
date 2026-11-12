"""Evidence-based Russian real-estate cards and licensed Telegram photo albums."""
from __future__ import annotations

import html
import ipaddress
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

KIND_NAMES = {
    "prodaja-stanova": "Продажа квартиры",
    "izdavanje-stanova": "Аренда квартиры",
    "prodaja-kuca": "Продажа дома",
}
MAX_PHOTOS = 5


def safe_https_url(value: str) -> bool:
    """Allow public, absolute HTTPS links; avoid local/credentialed destinations."""
    try:
        p = urlparse(value)
        host = p.hostname or ""
        if p.scheme != "https" or not host or p.username or p.password:
            return False
        if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(host)
            return address.is_global
        except ValueError:
            return "." in host and ".." not in host
    except ValueError:
        return False


def clean_text(value: str, max_length: int = 560) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()[:max_length]


def details_from_html(markup: str, base: str) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Facts as advertised, NOT independently verified. No copied long descriptions."""
    soup = BeautifulSoup(markup, "html.parser")
    meta = soup.find("meta", attrs={"name": "description"})
    description = clean_text(meta.get("content", "") if meta else "", 350)
    # Only the listing's own description is used; a site-wide nav may mention
    # unrelated features (parking/lift/renovation), so don't scan whole body.
    body = description.lower()
    location = ""
    breadcrumb = soup.select_one('[itemprop="addressLocality"]')
    if breadcrumb:
        location = clean_text(breadcrumb.get("content") or breadcrumb.get_text(" ", strip=True), 90)

    positive: list[str] = []
    negative: list[str] = []
    if re.search(r"\b(?:renoviran|renovirana|renovirano|kompletno renoviran)\b", body) and not re.search(
        r"\b(?:za renoviranje|potrebno renoviranje)\b", body
    ):
        positive.append("Указан ремонт")
    if re.search(r"\b(?:za renoviranje|potrebno renoviranje)\b", body):
        negative.append("В объявлении указан необходимый ремонт")
    if re.search(r"\b(?:ima lift|zgrada sa liftom|lift postoji)\b", body):
        positive.append("Указан лифт")
    if re.search(r"\b(?:nema lift|bez lifta)\b", body):
        negative.append("Указано отсутствие лифта")
    if re.search(r"\b(?:uknjižen|uknjižena|uknjiženo)\b", body):
        positive.append("Заявлена регистрация объекта (проверить документы)")
    if re.search(r"\b(?:sa terasom|ima terasu|poseduje terasu)\b", body):
        positive.append("Указана терраса")
    if re.search(r"\b(?:poslednji sprat|potkrovlje)\b", body):
        negative.append("Последний этаж или мансарда (по объявлению)")
    if re.search(r"\b(?:prizemlje|suteren)\b", body):
        negative.append("Приземный или цокольный этаж (по объявлению)")
    if re.search(r"\b(?:depozit obavezan|obavezan depozit)\b", body):
        negative.append("Указан обязательный депозит")

    photos: list[str] = []
    def add(raw: str) -> None:
        url = urljoin(base, html.unescape(raw.strip())) if raw else ""
        if not safe_https_url(url):
            return
        lower = urlparse(url).path.lower()
        if any(term in lower for term in ("logo", "avatar", "icon", "sprite", "placeholder")):
            return
        if url not in photos and len(photos) < MAX_PHOTOS:
            photos.append(url)

    # Structured gallery images are preferable to a generic social thumbnail.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            source = item.get("image", [])
            for entry in source if isinstance(source, list) else [source]:
                if isinstance(entry, str):
                    add(entry)
                elif isinstance(entry, dict) and isinstance(entry.get("url"), str):
                    add(entry["url"])
    for img in soup.select('main img, article img, [class*="gallery"] img'):
        source = img.get("data-src") or img.get("data-original") or img.get("src")
        if source:
            add(source)
    if not photos:
        og = soup.find("meta", attrs={"property": "og:image"})
        if og:
            add(og.get("content", ""))
    return location, description, tuple(positive), tuple(negative), tuple(photos)


def translate_short(text: str) -> str:
    """Optional short translation; never invent a paraphrase if translation fails."""
    text = clean_text(text, 350)
    if not text:
        return ""
    try:
        res = requests.get(
            "https://translate.googleapis.com/translate_a/t",
            params={"client": "dict-chrome-ex", "sl": "sr", "tl": "ru", "q": text},
            timeout=12,
        )
        res.raise_for_status()
        result = res.json()
        translated = result[0] if isinstance(result, list) and result else ""
        if isinstance(translated, str) and translated.strip() and translated.strip() != text:
            return clean_text(translated, 400)
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return ""


def _chunk_text(lines: list[str], remaining: int) -> list[str]:
    output = []
    for line in lines:
        if remaining <= 5:
            break
        if len(line) <= remaining:
            output.append(line)
            remaining -= len(line) + 1
        else:
            output.append(line[: max(0, remaining - 1)] + "…")
            break
    return output


def format_card(offer, now: datetime, translated: str = "") -> str:
    """A readable Russian Telegram message, source claims clearly qualified."""
    action = KIND_NAMES.get(offer.kind, "Недвижимость")
    amount = f"{offer.price_eur:,}".replace(",", " ")
    per = "/мес." if offer.kind == "izdavanje-stanova" else ""
    eur_per_m2 = f"{offer.unit_price:,.0f}".replace(",", " ")
    unit = "€/м²/мес." if per else "€/м²"
    location = clean_text(getattr(offer, "location", ""), 130) or "Район и адрес уточняются"
    short = translated or clean_text(getattr(offer, "description_ru", ""), 400)
    if not short:
        short = (
            f"Предлагается {('дом' if offer.kind == 'prodaja-kuca' else 'квартира')} "
            f"площадью {offer.area_m2:g} м². Характеристики, состояние и условия "
            "необходимо уточнить по оригинальному объявлению."
        )
    positives = [clean_text(v, 120) for v in getattr(offer, "pros", ()) if clean_text(v)]
    negatives = [clean_text(v, 120) for v in getattr(offer, "cons", ()) if clean_text(v)]
    if getattr(offer, "advertiser", "").startswith("Собственник"):
        positives.insert(0, "Размещено от собственника (по заявлению)")
    if not positives:
        positives = ["Точные преимущества пока не подтверждены"]
    if not negatives:
        negatives = ["Недостатки не указаны — состояние и расходы требуют проверки"]
    url = getattr(offer, "url", "")
    if not safe_https_url(url):
        raise ValueError("Listing URL must be a safe absolute HTTPS URL")
    sections = [
        f"🏠 <b>{html.escape(action)} · {html.escape(offer.city)}</b>",
        f"💶 <b>{amount} €{per}</b> · 📐 <b>{offer.area_m2:g} м²</b> ({eur_per_m2} {unit})",
        f"📍 <b>Расположение:</b> {html.escape(location)}",
        "",
        f"📝 <b>Описание:</b> {html.escape(short)}",
        "",
        "✅ <b>Плюсы:</b>",
        *["• " + html.escape(x) for x in positives[:4]],
        "",
        "⚠️ <b>Минусы и вопросы:</b>",
        *["• " + html.escape(x) for x in negatives[:4]],
        "",
        f"👤 <b>Продавец:</b> {html.escape(offer.advertiser)}",
        f"🗓 Обновлено: {offer.updated} · просмотрено {now:%d.%m.%Y %H:%M} (Белград)",
        "🔎 Доступность и документы не подтверждены; сведения из объявления, не техническая проверка.",
        f'🔗 <a href="{html.escape(url, quote=True)}">Смотреть оригинал и контакты</a>',
    ]
    # Keep Telegram below 4096 chars, with an intact link and qualification.
    message = "\n".join(sections)
    if len(message) > 3800:
        raise ValueError("Property card is too long; restrict source text fields")
    return message


def send_photos(session: requests.Session, token: str, chat_id: str, message_id: int,
                photo_urls: tuple[str, ...]) -> bool:
    """Photos only when separately licensed by the source/owner; no silent reposting."""
    selected = [url for url in photo_urls[:MAX_PHOTOS] if safe_https_url(url)]
    if not selected:
        return False
    method = "sendMediaGroup" if len(selected) > 1 else "sendPhoto"
    payload = {
        "chat_id": chat_id,
        "reply_parameters": {"message_id": message_id},
    }
    if len(selected) > 1:
        payload["media"] = [{"type": "photo", "media": url} for url in selected]
    else:
        payload["photo"] = selected[0]
    try:
        result = session.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=35,
        )
        if not result.ok:
            print(f"Telegram media HTTP {result.status_code}; listing text is still published.")
            return False
        return result.json().get("ok", False) is True
    except (requests.RequestException, ValueError):
        print("Telegram photo delivery failed; listing text is still published.")
        return False
