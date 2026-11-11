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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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


def relevant(article: Article) -> bool:
    title = normalized_title(article.title)
    summary = normalized_title(article.summary[:400])
    joined = f"{title} {summary}"
    return any(word in joined for word in SERBIA_WORDS)


def is_duplicate(article: Article, state: dict, threshold: float = 0.86) -> bool:
    if article_id(article) in state.get("seen", {}):
        return True
    title = normalized_title(article.title)
    for record in state.get("posted", []):
        old = record.get("title_norm", "")
        if old and difflib.SequenceMatcher(None, title, old).ratio() >= threshold:
            return True
    return False


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
        output.append(Article(source, title, url, snippet, ts))
    return output


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
        f"Источник: {html.escape(article.source)}</a>\n\n"
        "🇷🇸 <b>Сербия 24</b> | #НовостиСербии"
    )
    return result


def post_telegram(message: str, token: str, channel: str, preview_url: str = "") -> None:
    """Use Telegram's large webpage preview ABOVE the text when available.

    Telegram itself resolves the source website's thumbnail; the bot does not
    download or redistribute third-party photographs.
    """
    preview = {
        "is_disabled": False,
        "prefer_large_media": True,
        "show_above_text": True,
    }
    if preview_url:
        preview["url"] = preview_url
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message,
                "parse_mode": "HTML",
                "link_preview_options": preview,
            },
            timeout=20,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("Сбой сетевого запроса к Telegram") from None
    if response.status_code != 200 or not data.get("ok"):
        raise RuntimeError(
            f"Telegram rejected publication: HTTP {response.status_code} "
            f"({data.get('description', 'unknown error')})"
        )


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"seen": {}, "posted": []}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf8"))
        return {"seen": dict(state.get("seen", {})), "posted": list(state.get("posted", []))}
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Повреждён файл истории; публикация остановлена") from exc


def prune_state(state: dict, now: datetime) -> None:
    threshold = (now - timedelta(days=14)).timestamp()
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
        raise RuntimeError("Добавьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL в GitHub Secrets")

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
                post_telegram(message, token, channel, article.url)
            sent += 1
            stamp = now.timestamp()
            state["seen"][article_id(article)] = stamp
            state["posted"].append({
                "ts": stamp,
                "title_norm": normalized_title(article.title),
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
