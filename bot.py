"""Сербия 24: RSS-анонсы сербских СМИ -> перевод -> Telegram.

Публикует короткие сообщения со ссылкой на источник, не копируя полные статьи.
"""
from __future__ import annotations

import calendar
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

SERBIA_WORDS = (
    "srbij", "beograd", "novi sad", "novom sadu", "nis", "kragujevac", "subotic",
    "pancev", "zrenjanin", "cacak", "leskovac", "uzice", "sombor", "valjev",
    "kraljev", "vojvodin", "kosov", "vucic", "skupstin", "ministar", "vlada",
    "predsednik", "opstin", "gradonacel", "policij", "mup", "hapsen",
    "tuzilast", "sud", "izbor", "protest", "zakon", "propis", "dinara",
    "dinar", "cene", "cena", "poskup", "jeftin", "inflacij", "privred",
    "porez", "penzij", "plata", "bank", "kamata", "gorivo", "benzin",
    "dizel", "struj", "grejanj", "vodovod", "voda za pice", "saobracaj",
    "autoput", "putarin", "granic", "aerodrom", "voz", "autobus",
    "skol", "vrtic", "zdravstv", "bolnic", "dom zdravlja", "boravak",
    "radna dozvola", "nekretnin", "stanovi", "stanarin",
)


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


# Serbia's national news sites also publish many foreign-world headlines.
# The headline must relate to Serbia; a passing reference in a long article
# is insufficient for our local Russian-language Telegram channel.
SERBIA_HEADLINE_MARKERS = (
    "srbij", "beograd", "novi sad", "novom sadu", "novosad",
    "nisu", "nisa", "nis ", "kragujev", "subotic", "pancev", "zrenjanin",
    "sombor", "kraljev", "cacak", "leskov", "uzic", "valjev",
    "lazarevac", "obrenovac", "zemun", "vracar", "vozdovac",
    "vojvodin", "kosov", "vucic", "brnabic", "dacic", "vulin",
    "skupstin", "ministarstv", "narodn bank", "poštanska",
    "postanska", "mup", "dinara", "dinara", "dinari",
)
FOREIGN_TITLE_MARKERS = (
    "spanij", "madrid", "portugal", "lisabon", "francusk", "pariz",
    "nemack", "berlin", "italij", "rim", "austrij", "bec ",
    "britanij", "london", "englesk", "americ", "amerika",
    "sad ", "vasington", "njujork", "ukrajin", "kijev",
    "rusij", "moskv", "kin ", "peking", "japan", "tokij",
    "grck", "atin", "hrvatsk", "zagreb", "slovenij", "ljubljan",
    "madjarsk", "budimpest", "rumunij", "bukurest",
    "bugarsk", "sofij", "tursk", "istanbul", "ankara",
    "albanij", "tiran", "iran", "irak", "izrael", "gaza",
    "liban", "sirij", "sudan", "egipat", "kanad", "brazil",
    "indij", "pakistan", "svajcarsk", "brisel", "evropsk unij",
)
LOCAL_TOPIC_MARKERS = (
    "cen", "porez", "bank", "goriv", "struj", "grejanj", "poskup",
    "plata", "penzij", "policij", "hapsen", "protest", "zakon",
    "izbor", "skol", "vrtic", "saobrac", "put", "stan", "zdrav",
    "nagrad", "drzav", "radnik", "vlada", "ministar", "grad",
)


def relevant(article: Article) -> bool:
    title = normalized_title(article.title) + " "
    summary = normalized_title(article.summary[:450]) + " "
    title_local = any(marker in title for marker in SERBIA_HEADLINE_MARKERS)
    if title_local:
        return True
    # Reject e.g. "Protests in Spain" even if the source's excerpt mentions
    # Serbia or a local politician in passing.
    if any(marker in title for marker in FOREIGN_TITLE_MARKERS):
        return False
    # Otherwise require both a relevant local topic and a *clear*
    # Serbian geographic/person anchor in the short summary.
    return (
        any(marker in title for marker in LOCAL_TOPIC_MARKERS)
        and any(marker in summary for marker in SERBIA_HEADLINE_MARKERS)
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
    """Select up to three complete sentences from the RSS excerpt.

    Keep original facts, do not invent additional context or summarize an
    unrelated article. A short RSS entry may produce just one paragraph.
    """
    summary = clean_text(article.summary)
    if not summary or normalized_title(summary) == normalized_title(article.title):
        return ""
    summary = re.sub(
        r"\b(Pročitajte više|Procitajte vise|Čitaj više|Citaj vise)\b.*$",
        "", summary, flags=re.I,
    ).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]
    selected = []
    for sentence in sentences[:3]:
        if len(" ".join(selected + [sentence])) > 420:
            break
        selected.append(sentence)
    excerpt = " ".join(selected)
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
) -> None:
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
            return
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
        return {"seen": {}, "posted": []}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf8"))
        return {"seen": dict(state.get("seen", {})), "posted": list(state.get("posted", []))}
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Повреждён файл истории; публикация остановлена") from exc


def prune_state(state: dict, now: datetime) -> None:
    threshold = (now - timedelta(days=60)).timestamp()
    state["seen"] = {k: v for k, v in state["seen"].items() if float(v) > threshold}
    state["posted"] = [p for p in state["posted"] if float(p.get("ts", 0)) > threshold]


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
            if dry_run:
                LOG.info("DRY_RUN: %s", message)
            else:
                image_url = article_photo(article)
                caption = photo_caption(article, title_ru, summary_ru)
                post_telegram(message, token, channel, article.url, image_url, caption)
            sent += 1
            stamp = now.timestamp()
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
