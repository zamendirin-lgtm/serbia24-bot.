"""Сербия 24: RSS-анонсы сербских СМИ -> перевод -> Telegram.

Публикует короткие сообщения со ссылкой на источник, не копируя полные статьи.
"""
from __future__ import annotations

import calendar
from io import BytesIO
import difflib
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from unidecode import unidecode

LOG = logging.getLogger("serbia24")
STATE_FILE = Path(__file__).parent / "data" / "seen.json"
TZ = ZoneInfo("Europe/Belgrade")

FEEDS = {
    "RTS": "https://www.rts.rs/vesti/rss.html",
    "N1": "https://n1info.rs/feed/",
    "Danas": "https://www.danas.rs/feed/",
    "B92": "https://www.b92.net/rss/b92/info",
}

PUBLISH_START_HOUR = 8
PUBLISH_END_HOUR = 22  # no posts at or after 22:00 Belgrade local time


def publication_allowed(now: datetime) -> bool:
    """Honor quiet hours even during daylight-saving transitions and manual runs."""
    return PUBLISH_START_HOUR <= now.astimezone(TZ).hour < PUBLISH_END_HOUR


@dataclass(frozen=True)
class Article:
    source: str
    title: str
    url: str
    summary: str
    published_ts: float
    image_url: str = ""


def clean_text(value: str) -> str:
    result = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(result)).strip()


def normalized_title(value: str) -> str:
    value = unidecode(value or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def canonical_url(raw: str) -> str:
    u = urlsplit((raw or "").strip())
    kept = [
        (k, v) for k, v in parse_qsl(u.query)
        if not k.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    return urlunsplit(
        (u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), urlencode(kept), "")
    )


def article_id(article: Article) -> str:
    return hashlib.sha256(canonical_url(article.url).encode("utf8")).hexdigest()[:24]


def recent_enough(article: Article, now: datetime, hours: int = 8) -> bool:
    return 0 <= now.timestamp() - article.published_ts <= hours * 3600


# We cover Serbia proper, not the worldwide-news section of Serbia-based
# publishers. Exact-word handling avoids confusing "nisu" (= are not) with
# Niš or a passing mention of a Serbian person in foreign politics.
SERBIA_LOCATIONS = (
    "srbij", "beograd", "novosad", "vojvodin", "kragujev", "subotic",
    "pancev", "zrenjanin", "sombor", "kraljev", "cacak", "leskov",
    "uzic", "valjev", "lazarevac", "obrenovac", "zemun", "vracar",
    "vozdovac", "loznic", "pozeg", "arilj", "novipazar", "krusev",
    "jagod", "vranj", "sremsk", "smederev", "prokupl", "bor",
    "kikind", "pirot", "ruma", "indjij", "back", "zlatibor",
    "mladenov", "cukaric", "palilul",
)
SERBIA_ACTORS = (
    "vucic", "brnabic", "dacic", "vulin", "ruzic", "mup srbije",
    "skupstina srbije", "vlada srbije", "putevi srbije",
    "narodna banka srbije", "nbs", "eps",
)
KOSOVO_PLACES = (
    "kosovo", "kosova", "kosov", "zubin potok", "zubinom potoku",
    "pristin", "mitrovic", "lep osavic", "leposavic",
    "ibarski kolasin", "ibarskog kolasina", "drenic",
    "gazivode", "metohij",
)
FOREIGN_STORIES = (
    "tramp", "trump", "teheran", "iran", "iranu", "amerika",
    "americ", "sad", "spanij", "madrid", "ukrajin", "rusij",
    "putin", "zelensk", "evropsk unij", "bliski istok",
    "francusk", "italij", "nemack", "kina", "izrael",
    "gaza", "liban", "sudanu",
)
LOCAL_TOPIC_MARKERS = (
    "cen", "porez", "bank", "goriv", "struj", "grejanj", "poskup",
    "plata", "penzij", "policij", "hapsen", "protest", "zakon",
    "izbor", "skol", "vrtic", "saobrac", "put", "stan", "zdrav",
    "radnik", "vlada", "ministar", "grad", "sport", "fabrika",
)


def has_anchored_word(text: str, word: str) -> bool:
    """Match normalized words, not accidental substrings (nisu ≠ Niš)."""
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text))


def contains_anchor(text: str, stems: tuple[str, ...]) -> bool:
    words = text.split()
    for stem in stems:
        if " " in stem:
            if stem in text:
                return True
        elif len(stem) <= 3:
            if has_anchored_word(text, stem):
                return True
        elif any(word.startswith(stem) for word in words):
            return True
    return False


def has_serbia_anchor(text: str) -> bool:
    words = text.split()
    if any(w in words for w in ("nis", "nisa", "nisu")):
        # Only use "Niš" with clearer context; "nisu" always means "are not".
        if "nis" in words or "nisa" in words:
            return True
    if "novi sad" in text or "novom sadu" in text:
        return True
    return contains_anchor(text, SERBIA_LOCATIONS) or contains_anchor(text, SERBIA_ACTORS)


def relevant(article: Article) -> bool:
    title = normalized_title(article.title)
    summary = normalized_title(article.summary[:450])

    # Kosovo-only stories require a Serbian state/institutional angle *in
    # the headline*, not merely an incidental mention of ethnic Serbs.
    if contains_anchor(title, KOSOVO_PLACES):
        if not contains_anchor(title, SERBIA_ACTORS):
            return False
        return contains_anchor(title, SERBIA_LOCATIONS + SERBIA_ACTORS)

    if has_serbia_anchor(title):
        return True

    # Worldwide headlines can quote Serbian media in a generic summary.
    if contains_anchor(title, FOREIGN_STORIES):
        return False

    # For unanchored titles, allow the story only when local topical news
    # and a clear Serbia location/institution appear in its short excerpt.
    return (
        contains_anchor(title, LOCAL_TOPIC_MARKERS)
        and has_serbia_anchor(summary)
    )


# Use the original Serbian titles, before translation. This also works across
# Cyrillic/Latin, because normalized_title() transliterates all text to Latin.
EVENT_STOPWORDS = frozenset("""
    a ako ali bi bila bilo bio biti ce cemo ces da do dok i ili iz kao kada
    ko koja koje koji koliko kod kome li na nakon naj naje ne nego njen njegov
    njihov njima niko niti njom o od oko on ona oni ono ove ovaj ovo ovim
    pa po posle pre prema pri protiv sa se si smo su sam ste sto sta tako te
    time to tokom u uz vec vise za zbog kako gde gde god sada danas juce
    rekao rekla receno kazao saopstio saopstila izjavio izjavila najavio
    najavila prenosi prenose navodi navela vesti vest foto video godine
    godinu godina novi nova novo novog novim najnovije sve svih svih
""".split())
# These terms recur in many unrelated Serbian headlines; overlapping only
# on "Belgrade / police / accident" must never mark a different event as a copy.
COMMON_NEWS_TERMS = frozenset("""
    srbij beogr novog novi grad vucic vlada izbor zakon minist saobr
    nesre povre polici osobe osobi ljudi protes radni banka cen goriv
    vlast drzav javno vest stude zdrav sport fabri stanov
""".split())
NEGATION_WORDS = frozenset(("ne", "nije", "nisu", "nema", "nismo", "bez", "nikad", "nece", "necu", "necemo"))
OPPOSING_EVENTS = (
    ("otvor", "zatvor"),  # opened vs shut down
    ("povec", "smanj"),  # increased vs decreased
    ("usvoj", "odbij"),  # approved vs rejected
    ("pobed", "izgub"),  # won vs lost
    ("pokre", "obust"),  # started vs halted
    ("odob", "zabra"),  # approved vs prohibited
)


def conflicting_event_details(a: str, b: str) -> bool:
    words_a, words_b = set(a.split()), set(b.split())
    if bool(words_a & NEGATION_WORDS) != bool(words_b & NEGATION_WORDS):
        return True
    nums_a = {w for w in words_a if w.isdigit()}
    nums_b = {w for w in words_b if w.isdigit()}
    if nums_a and nums_b and nums_a != nums_b:
        return True
    for left, right in OPPOSING_EVENTS:
        if (
            any(w.startswith(left) for w in words_a)
            and any(w.startswith(right) for w in words_b)
        ) or (
            any(w.startswith(right) for w in words_a)
            and any(w.startswith(left) for w in words_b)
        ):
            return True
    return False


def event_terms(title: str) -> set[str]:
    """Lightweight, free keyword fingerprint tolerant of Serbian inflections."""
    text = normalized_title(title)
    result = set()
    for word in text.split():
        if word in EVENT_STOPWORDS or word.isdigit():
            continue
        if len(word) < 4 and word not in {"sns", "nis", "mup", "eps", "nbs", "eu"}:
            continue
        # e.g. fabrika/fabrike, Zrenjanin/Zrenjaninu, Srbiji/Srbija.
        result.add(word[:5] if len(word) > 5 else word)
    return result


def same_event_title(a: str, b: str, threshold: float = 0.86) -> bool:
    """Detect very similar headlines and substantially reworded same stories.

    Conservative with numbers and negation so a price change, new court
    decision or reverse statement can remain a separate development.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    if conflicting_event_details(a, b):
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
        return True
    first, second = event_terms(a), event_terms(b)
    if not first or not second:
        return False
    shared = first & second
    if len(shared) < 3:
        return False
    jaccard = len(shared) / len(first | second)
    containment = len(shared) / min(len(first), len(second))
    if jaccard >= 0.78 and containment >= 0.85:
        return True
    if len(shared) < 4:
        return False
    if jaccard >= 0.69 and containment >= 0.75:
        return True
    distinctive = shared - COMMON_NEWS_TERMS
    return (
        len(distinctive) >= 1
        and jaccard >= 0.47
        and containment >= 0.72
    )


def same_event_summary(article: Article, record: dict, title_norm: str) -> bool:
    """Use RSS excerpts only as a confirmation of already overlapping titles."""
    old_summary = record.get("summary_norm", "")
    if not old_summary or not article.summary:
        return False
    old_title = record.get("title_norm", "")
    if conflicting_event_details(title_norm, old_title):
        return False
    intersection = event_terms(title_norm) & event_terms(old_title)
    if len(intersection) < 2:
        return False
    summary_norm = normalized_title(article.summary[:500])
    a, b = event_terms(summary_norm), event_terms(old_summary)
    if len(a & b) < 6 or not a or not b:
        return False
    return (
        len(a & b) / len(a | b) >= 0.76
        and len(a & b) / min(len(a), len(b)) >= 0.84
    )


def is_duplicate(article: Article, state: dict, threshold: float = 0.86) -> bool:
    """Catch repeated URLs and reworded coverage across all RSS sources."""
    if article_id(article) in state.get("seen", {}):
        return True
    title = normalized_title(article.title)
    for record in state.get("posted", []):
        if same_event_title(title, record.get("title_norm", ""), threshold):
            return True
        if same_event_summary(article, record, title):
            return True
    return False


def normal_image_url(raw: str, base: str = "") -> str:
    """Accept only HTTPS image URLs obtained from publisher RSS/HTML."""
    url = urljoin(base, html.unescape((raw or "").strip()))
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or not parts.netloc or parts.username:
        return ""
    if parts.hostname in {"localhost", "127.0.0.1", "::1"}:
        return ""
    if parts.path.lower().endswith((".svg", ".gif", ".ico")):
        return ""
    return url


def rss_photo(entry, article_url: str) -> str:
    """Direct photo attached to RSS (no Telegram page-title overlay)."""
    for field in ("media_content", "media_thumbnail", "enclosures"):
        for item in entry.get(field, []):
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("type", ""))
            if media_type and not media_type.startswith("image/"):
                continue
            image_url = normal_image_url(item.get("url", item.get("href", "")), article_url)
            if image_url:
                return image_url
    description = BeautifulSoup(
        entry.get("summary", "") or "", "html.parser"
    )
    img = description.find("img", src=True)
    if img:
        return normal_image_url(img.get("src", ""), article_url)
    return ""


def parse_feed(source: str, payload: bytes) -> list[Article]:
    parsed = feedparser.parse(payload)
    output = []
    for entry in parsed.entries[:60]:
        title = clean_text(entry.get("title", ""))
        url = canonical_url(entry.get("link", ""))
        date = entry.get("published_parsed") or entry.get("updated_parsed")
        if not date or not title or not url.startswith("https://"):
            continue
        ts = calendar.timegm(date)
        snippet = clean_text(entry.get("summary", ""))
        image_url = rss_photo(entry, url)
        output.append(Article(source, title, url, snippet, ts, image_url))
    return output


def article_photo(article: Article) -> str:
    """Find publisher's original photo without adding the page's English headline.

    It cannot strip text that is part of the actual image pixels.
    """
    if article.image_url:
        return article.image_url
    try:
        r = requests.get(
            article.url, timeout=14, headers={"User-Agent": "Mozilla/5.0 Serbia24Bot/1.1"},
        )
        r.raise_for_status()
        if "html" not in r.headers.get("Content-Type", "").lower():
            return ""
        # Only parse the first 2 MB of the webpage.
        soup = BeautifulSoup(r.content[:2_000_000], "html.parser")
        for attr, name in (
            ("property", "og:image"),
            ("name", "twitter:image"),
            ("property", "article:image"),
        ):
            tag = soup.find("meta", attrs={attr: name})
            if tag and tag.get("content"):
                image_url = normal_image_url(tag["content"], article.url)
                if image_url:
                    return image_url
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("Не удалось найти фото у %s: %s", article.source, type(exc).__name__)
    return ""


def photo_url_key(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf8")).hexdigest()[:24]


def image_dhash(image_bytes: bytes) -> str:
    """64-bit visual fingerprint: resistant to resizing/compression."""
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("L").resize((9, 8))
        pixels = list(image.getdata())
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
        return f"{bits:016x}"


def fetch_image_fingerprint(photo_url: str) -> str:
    """Download only a few MB for repeat-photo detection, never save the photo."""
    try:
        with requests.get(
            photo_url,
            timeout=14,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (Serbia24/1.0)"},
        ) as response:
            response.raise_for_status()
            if int(response.headers.get("Content-Length") or "0") > 3_000_000:
                return ""
            chunks, count = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                count += len(chunk)
                if count > 3_000_000:
                    return ""
                chunks.append(chunk)
        return image_dhash(b"".join(chunks))
    except (requests.RequestException, OSError, UnidentifiedImageError, ValueError) as exc:
        LOG.info("Пропускаем визуальное сравнение фото: %s", type(exc).__name__)
        return ""


def is_repeated_photo(photo_url: str, fingerprint: str, state: dict) -> bool:
    if photo_url_key(photo_url) in state.get("photos", {}):
        return True
    if not fingerprint:
        return False
    try:
        bits = int(fingerprint, 16)
        for prior in state.get("phashes", {}):
            if (bits ^ int(prior, 16)).bit_count() <= 3:
                return True
    except (ValueError, TypeError):
        return False
    return False


def fetch_news() -> list[Article]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Serbia24NewsBot/1.0 RSS reader",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    all_news = []
    for source, url in FEEDS.items():
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            parsed = parse_feed(source, response.content)
            LOG.info("RSS %s: %s статей", source, len(parsed))
            all_news.extend(parsed)
        except Exception as exc:
            LOG.warning("Источник %s временно недоступен: %s", source, exc)
    return all_news


def prepare_summary(article: Article) -> str:
    """One or two complete factual sentences; never publish RSS teaser questions."""
    summary = clean_text(article.summary)
    if not summary or normalized_title(summary) == normalized_title(article.title):
        return ""
    summary = re.sub(
        r"\b(Pročitajte više|Procitajte vise|Čitaj više|Citaj vise|Više na)\b.*$",
        "", summary, flags=re.I,
    ).strip()
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", summary) if x.strip()]
    selected = []
    for sentence in sentences[:4]:
        # Editorial question/teaser is not factual reporting.
        if "?" in sentence or "!" in sentence:
            continue
        if len(" ".join(selected + [sentence])) > 300:
            break
        selected.append(sentence)
        if len(selected) >= 2:
            break
    excerpt = " ".join(selected)
    if excerpt.endswith((",", ":", ";", "-")):
        return ""
    return excerpt if len(excerpt) >= 35 else ""


class FreeTranslator:
    """Free keyless translation with a secondary provider as fallback.

    These are public, unofficial/community endpoints; neither has an SLA.
    """

    def translate(self, text: str) -> str:
        if not text:
            return ""
        try:
            response = requests.get(
                "https://translate.googleapis.com/translate_a/t",
                params={
                    "client": "dict-chrome-ex",
                    "sl": "sr",
                    "tl": "ru",
                    "q": text,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            translated = data[0] if data and isinstance(data[0], str) else ""
            if translated and translated.strip() != text.strip():
                return translated.strip()
        except (ValueError, IndexError, KeyError, requests.RequestException):
            pass

        # MyMemory accepts up to 500 bytes per segment, anonymous quota 5000 chars/day.
        if len(text.encode("utf-8")) > 490:
            raise ValueError("Слишком длинный текст для бесплатного резервного переводчика")
        try:
            response = requests.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": "sr|ru"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if int(data.get("responseStatus", 0)) != 200:
                raise ValueError("MyMemory отказал в переводе")
            translated = html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()
            if translated and translated != text.strip() and "MYMEMORY WARNING" not in translated.upper():
                return translated
        except (ValueError, requests.RequestException) as exc:
            raise RuntimeError("Оба бесплатных переводчика сейчас недоступны") from None
        raise RuntimeError("Бесплатный перевод недоступен")


def translate_article(article: Article, translator: FreeTranslator) -> tuple[str, str]:
    title = translator.translate(article.title)
    if not title:
        raise ValueError("Не удалось перевести заголовок")
    summary_sr = prepare_summary(article)
    try:
        summary_ru = translator.translate(summary_sr) if summary_sr else ""
    except Exception:
        LOG.warning("Не удалось перевести анонс — публикуем только заголовок")
        summary_ru = ""
    return title, summary_ru


def news_emoji(article: Article, title_ru: str) -> str:
    """Small, restrained topic indicator; avoid sensationalism."""
    title = normalized_title(article.title + " " + title_ru)
    categories = (
        (("banka", "banci", "banke", "bank"), "🏦"),
        (("goriv", "benzin", "dizel", "fuel"), "⛽"),
        (("vreme", "nevrem", "meteorolog"), "🌦️"),
        (("saobrac", "autoput", "putarin"), "🚗"),
        (("skol", "vrtic", "obrazovan"), "🎓"),
        (("zdravst", "bolnic", "lekar"), "🏥"),
        (("nekretn", "stanovi", "stanarina"), "🏠"),
        (("cena", "cene", "poskupl", "inflacij", "porez"), "💶"),
        (("izbor", "skupstin", "vlada", "ministar"), "🏛️"),
    )
    for keywords, emoji in categories:
        if any(word in title for word in keywords):
            return emoji
    return "🇷🇸"


def format_post(article: Article, title_ru: str, summary_ru: str) -> str:
    """Brand-consistent Telegram post, HTML escaped and linked to its source."""
    emoji = news_emoji(article, title_ru)
    result = f"{emoji} <b>{html.escape(title_ru)}</b>\n\n"
    if summary_ru.strip():
        # Use real sentence boundaries only; a short excerpt stays one paragraph.
        summary = summary_ru.strip()
        sentences = re.split(r"(?<=[.!?])\s+", summary)
        if len(sentences) >= 3:
            split = len(sentences) // 2
            summary = " ".join(sentences[:split]) + "\n\n" + " ".join(sentences[split:])
        result += f"{html.escape(summary)}\n\n"
    result += (
        f'🔗 <a href="{html.escape(article.url, quote=True)}">'
        f"Источник: {html.escape(article.source)}</a>"
    )
    return result


def photo_caption(article: Article, title_ru: str, summary_ru: str) -> str:
    """Telegram photo captions are limited to 1024 visible characters.

    Keep source attribution, the Russian headline and as much summary as fits.
    """
    title = title_ru.strip()[:220]
    emoji = news_emoji(article, title_ru)
    first = f"{emoji} <b>{html.escape(title)}</b>\n\n"
    ending = (
        f'\n\n🔗 <a href="{html.escape(article.url, quote=True)}">'
        f"Источник: {html.escape(article.source)}</a>"
    )
    # HTML tags are not counted toward Telegram's visible character limit;
    # 800 visible characters leaves room for all normal source URLs.
    budget = max(0, 800 - len(title) - len(article.source))
    summary = (summary_ru or "").strip()[:budget]
    return first + html.escape(summary) + ending


def telegram_api(method: str, token: str, payload: dict, timeout: int = 25) -> tuple[bool, str]:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        return False, "Ошибка соединения с Telegram"
    if response.status_code != 200 or not data.get("ok"):
        return False, str(data.get("description", "Ошибка Telegram"))
    return True, ""


def post_telegram(
    message: str,
    token: str,
    channel: str,
    preview_url: str = "",
    photo_url: str = "",
    caption: str = "",
) -> bool:
    """Send the source photo with OUR Russian text, not a webpage preview.

    Page-title metadata from the publisher (which can be in English) is never
    displayed. If the photograph itself contains letters, they remain part of
    the original image; this code does not manipulate or fabricate imagery.
    """
    if photo_url and caption:
        success, error = telegram_api(
            "sendPhoto",
            token,
            {
                "chat_id": channel,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
                "show_caption_above_media": False,
            },
            timeout=30,
        )
        if success:
            return True
        LOG.warning("Telegram не принял исходное фото; публикуем текст без предпросмотра: %s", error)

    # Do not show auto-generated article previews, which inject foreign
    # title/description above or below the post.
    success, error = telegram_api(
        "sendMessage",
        token,
        {
            "chat_id": channel,
            "text": message,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
    )
    if not success:
        raise RuntimeError(f"Telegram publication failed: {error}")
    return False


def verify_telegram_bot(token: str, channel: str) -> None:
    """Fail safely before publishing if the bot lacks channel post permission."""
    def api(method: str, params: dict | None = None) -> dict:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{token}/{method}",
                params=params or {},
                timeout=15,
            )
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError(f"Не удалось связаться с Telegram ({method})") from None
        if response.status_code != 200 or not payload.get("ok"):
            description = payload.get("description", "unknown error")
            raise RuntimeError(f"Telegram {method}: {description}")
        return payload["result"]

    me = api("getMe")
    if not me.get("is_bot") or not me.get("id"):
        raise RuntimeError("Указанный токен не принадлежит Telegram-боту")
    member = api(
        "getChatMember", {"chat_id": channel, "user_id": me["id"]}
    )
    status = member.get("status")
    if status == "creator":
        return
    if status != "administrator" or not member.get("can_post_messages", False):
        raise RuntimeError(
            "Добавьте бота администратором канала с правом «Публиковать сообщения»"
        )
    LOG.info("Подтверждены права публикации в канале %s", channel)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"seen": {}, "posted": [], "photos": {}, "phashes": {}}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf8"))
        return {
            "seen": dict(state.get("seen", {})),
            "posted": list(state.get("posted", [])),
            "photos": dict(state.get("photos", {})),
            "phashes": dict(state.get("phashes", {})),
        }
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Повреждён файл истории; публикация остановлена") from exc


def prune_state(state: dict, now: datetime) -> None:
    threshold = (now - timedelta(days=60)).timestamp()
    for field in ("seen", "photos", "phashes"):
        state.setdefault(field, {})
        state[field] = {
            k: v for k, v in state[field].items() if float(v) > threshold
        }
    state["posted"] = [
        p for p in state["posted"] if float(p.get("ts", 0)) > threshold
    ]


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    temp.replace(STATE_FILE)


def run() -> None:
    now = datetime.now(timezone.utc)
    state = load_state()
    prune_state(state, now)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.getenv("TELEGRAM_CHANNEL", "").strip()
    dry_run = os.getenv("DRY_RUN", "0").strip() == "1"
    if not publication_allowed(now):
        LOG.info("Тихие часы в Белграде (22:00–08:00): публикаций не будет")
        return
    if not dry_run and (not token or not channel):
        raise RuntimeError("Задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL")

    if not dry_run:
        verify_telegram_bot(token, channel)

    now_local_date = now.astimezone(TZ).date()
    daily_limit = max(1, int(os.getenv("DAILY_LIMIT", "10")))
    per_run_limit = max(1, int(os.getenv("PER_RUN_LIMIT", "2")))
    posted_today = sum(
        1 for p in state["posted"]
        if datetime.fromtimestamp(float(p["ts"]), TZ).date() == now_local_date
    )
    remaining = min(per_run_limit, daily_limit - posted_today)
    if remaining <= 0:
        LOG.info("Дневной лимит %s достигнут", daily_limit)
        return

    candidates = [a for a in fetch_news() if recent_enough(a, now) and relevant(a)]
    candidates.sort(key=lambda a: a.published_ts, reverse=True)
    LOG.info("Подходящих свежих новостей: %s", len(candidates))
    translator = FreeTranslator()
    sent = 0
    for article in candidates:
        if sent >= remaining:
            break
        if is_duplicate(article, state):
            continue
        try:
            title_ru, summary_ru = translate_article(article, translator)
            message = format_post(article, title_ru, summary_ru)
            sent_image = False
            image_url = ""
            fingerprint = ""
            if dry_run:
                LOG.info("DRY_RUN: %s", message)
            else:
                image_url = article_photo(article)
                if image_url:
                    # Skip repeating a visual from another story, even if its
                    # article link and headline are different.
                    if photo_url_key(image_url) in state.get("photos", {}):
                        LOG.info("Фото уже использовалось: %s", article.source)
                        image_url = ""
                    else:
                        fingerprint = fetch_image_fingerprint(image_url)
                        if is_repeated_photo(image_url, fingerprint, state):
                            LOG.info("Повторяющаяся фотография: %s", article.source)
                            image_url = ""
                caption = photo_caption(article, title_ru, summary_ru)
                sent_image = post_telegram(
                    message, token, channel, article.url, image_url, caption
                )
            sent += 1
            stamp = now.timestamp()
            if sent_image and image_url:
                state.setdefault("photos", {})[photo_url_key(image_url)] = stamp
                if fingerprint:
                    state.setdefault("phashes", {})[fingerprint] = stamp
            state["seen"][article_id(article)] = stamp
            state["posted"].append({
                "ts": stamp,
                "title_norm": normalized_title(article.title),
                "summary_norm": normalized_title(article.summary[:500]),
                "source": article.source,
            })
            if not dry_run:
                save_state(state)
            LOG.info("Публикация %s/%s: %s (%s)", sent, remaining, article.title[:60], article.source)
            time.sleep(2)
        except Exception as exc:
            LOG.warning("Пропущена новость %s: %s", article.title[:70], exc)
    LOG.info("Всего новых публикаций: %s", sent)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run()
    except Exception:
        LOG.exception("Ошибка выполнения")
        sys.exit(1)
