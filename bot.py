"""Сербия 24: RSS-анонсы сербских СМИ -> перевод -> Telegram.

Публикует короткие сообщения со ссылкой на источник, не копируя полные статьи.
"""
from __future__ import annotations

import calendar
from collections import Counter
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
import trafilatura
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
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
    "mladenov", "cukaric", "palilul", "kosjer",
)
SERBIA_ACTORS = (
    "vucic", "brnabic", "dacic", "vulin", "ruzic", "mup srbije",
    "skupstina srbije", "vlada srbije", "putevi srbije",
    "narodna banka srbije", "nbs", "eps",
)
KOSOVO_PLACES = (
    "kosovo", "kosova", "kosov", "zubin potok", "zubinom potoku",
    "pristin", "kosovska mitrovica", "lep osavic", "leposavic",
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


def has_serbia_anchor(text: str, original: str = "") -> bool:
    # "Nišu" loses its accent under transliteration and becomes "nisu",
    # identical to common Serbian word "nisu" (= are not). Only trust
    # the proper accented or Cyrillic spelling as a city reference.
    if re.search(r"\b(?:Niš(?:u|a|em)?|Ниш(?:у|а|ем)?)\b", original, re.I):
        return True
    if re.search(r"\b(?:u|iz|kod)\s+nis(?:u|a)?\b", text):
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

    if has_serbia_anchor(title, article.title):
        return True

    # Worldwide headlines can quote Serbian media in a generic summary.
    if contains_anchor(title, FOREIGN_STORIES):
        return False

    # For unanchored titles, allow the story only when local topical news
    # and a clear Serbia location/institution appear in its short excerpt.
    return (
        contains_anchor(title, LOCAL_TOPIC_MARKERS)
        and has_serbia_anchor(summary, article.summary[:450])
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
    host = (parts.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return ""
    # Danas RSS sometimes inserts the SAME YouTube video interview in the
    # summary of many unrelated news stories. It is NOT their photograph.
    if (host == "youtu.be" or host == "youtube.com" or
        host.endswith(".youtube.com") or host.endswith(".youtube-nocookie.com") or
        host == "vimeo.com" or host.endswith(".vimeo.com") or
        "/embed/" in parts.path.lower()):
        return ""
    if parts.path.lower().endswith((".svg", ".gif", ".ico", ".mp4", ".webm", ".m3u8")):
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


EDITORIAL_SKIP_PHRASES = (
    "procitajte vise", "citajte vise", "pogledajte video", "pratite nas",
    "podelite vest", "pretplatite se", "vise informacija",
    "povezane vesti", "izvor fotografije", "procitajte jos",
    "pise danas", "najnovije vesti", "pratite uzivo", "saznajte",
    "kliknite", "pogledajte galeriju", "na nasem portalu",
)


def split_news_sentences(text: str) -> list[str]:
    """Respect Serbian years/initials to avoid detached 'godine' fragments."""
    text = clean_text(text)
    text = re.sub(r"(\d{4})\.(?=\s+godine\b)", r"\1<YEAR_DOT>", text, flags=re.I)
    text = re.sub(
        r"\b([A-ZА-Я])\.\s*([A-ZА-Я])\.",
        r"\1<INITIAL_DOT> \2<INITIAL_DOT>", text,
    )
    pieces = re.split(r"(?<=[.!?])\s+", text)
    return [
        s.replace("<YEAR_DOT>", ".").replace("<INITIAL_DOT>", ".").strip()
        for s in pieces if s.strip()
    ]


def factual_sentence(sentence: str, title: str = "") -> bool:
    norm = normalized_title(sentence)
    if not 45 <= len(sentence) <= 440 or "?" in sentence:
        return False
    if any(phrase in norm for phrase in EDITORIAL_SKIP_PHRASES):
        return False
    if sentence[-1] not in ".!…":
        return False
    if re.search(r"https?://|www\.|@\w+", sentence, re.I):
        return False
    if title and difflib.SequenceMatcher(None, norm, normalized_title(title)).ratio() > 0.92:
        return False
    return True


def extract_article_paragraphs(article_html: str | bytes) -> list[str]:
    """Read real publisher prose, preserving encoding and excluding site chrome."""
    try:
        body = trafilatura.extract(
            article_html,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_precision=True,
        )
    except Exception:
        body = None
    if body:
        blocks = [clean_text(p) for p in re.split(r"\n+", body) if clean_text(p)]
        if blocks:
            return blocks
    soup = BeautifulSoup(article_html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "form", "iframe"]):
        tag.decompose()
    for selector in (
        "article", "[itemprop='articleBody']", ".article-body",
        ".entry-content", ".post-content",
    ):
        container = soup.select_one(selector)
        if container:
            paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in container.select("p")]
            if len(paragraphs) >= 2:
                return [x for x in paragraphs if x]
    return []


def select_news_paragraphs(blocks: list[str], headline: str) -> list[str]:
    """Keep the opening, closely related facts; never stitch distant topics."""
    # Some sites flatten all HTML paragraphs into a single text block.
    if len(blocks) == 1:
        blocks = split_news_sentences(blocks[0])
    title_terms = event_terms(headline) - COMMON_NEWS_TERMS
    paras = []
    first_terms = set()
    last_source_index = -1
    for block_index, block in enumerate(blocks[:9]):
        sentences = []
        for sentence in split_news_sentences(block):
            if not factual_sentence(sentence, headline):
                continue
            if not sentences and len(sentence) > 360:
                continue
            trial = " ".join(sentences + [sentence])
            if len(trial) > 330:
                break
            if sentence not in sentences:
                sentences.append(sentence)
            if len(sentences) >= 2:
                break
        if not sentences:
            continue
        paragraph = " ".join(sentences)
        # Sentence fragments after a year abbreviation (e.g. "godine...")
        # should never become standalone explanatory paragraphs.
        if paragraph[0].islower():
            continue
        norm = normalized_title(paragraph)
        if not paras:
            # Opening a post with 'he said' or 'according to him' makes it
            # impossible to understand who is speaking.
            if re.match(r"^(po njegovim recima|po njenim recima|on je|ona je|dodao je|kako je naveo)", norm):
                continue
            overlap = event_terms(paragraph) & title_terms
            if len(title_terms) >= 3 and len(overlap) < 1:
                continue
            first_terms = event_terms(paragraph)
        else:
            # Follow-up sentences from *adjacent* source paragraphs may use
            # synonyms or pronouns. Distant material needs explicit matching
            # headline terms, otherwise it risks joining unrelated topics.
            distance = block_index - last_source_index
            common = event_terms(paragraph) & title_terms
            required = 2 if len(title_terms) >= 5 else 1
            if (distance > 1 or len(paras) >= 2) and len(common) < required:
                continue
        paras.append(paragraph)
        last_source_index = block_index
        if len(paras) >= 3:
            break

    if len(paras) < 2 or len(" ".join(paras)) < 165:
        return []
    return paras


def fetch_editorial_paragraphs(article: Article) -> list[str]:
    """Read the publisher story for context, not just a short RSS teaser."""
    try:
        response = requests.get(
            article.url, timeout=16,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Serbia24NewsReader/1.1)",
                "Accept-Language": "sr-RS,sr;q=0.9",
            },
        )
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type", "").lower():
            return []
        # Avoid huge pages; text article extraction handles first few MB.
        # Let the extractor detect HTML charset from the original bytes.
        paragraphs = extract_article_paragraphs(response.content[:2_000_000])
        result = select_news_paragraphs(paragraphs, article.title)
        if result:
            return result
        LOG.info("Недостаточно фактов в тексте статьи: %s", article.source)
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        LOG.info("Недоступен текст статьи %s: %s", article.source, type(exc).__name__)
    return []


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
    """Require a substantive, readable story, otherwise skip the article."""
    paragraphs_sr = fetch_editorial_paragraphs(article)

    # Emergency fallback: complete factual RSS sentences only, never teaser.
    if not paragraphs_sr:
        fallback = prepare_summary(article)
        paragraphs_sr = select_news_paragraphs([fallback], article.title) if fallback else []
    if len(paragraphs_sr) < 2:
        raise ValueError("Слишком мало проверяемых фактов для полноценной новости")

    title_ru = translator.translate(article.title)
    if not title_ru or title_ru.strip() == article.title.strip():
        raise ValueError("Не удалось перевести заголовок")

    translated = []
    for paragraph in paragraphs_sr:
        ru = (translator.translate(paragraph) or "").strip()
        if not ru or ru == paragraph.strip():
            raise ValueError("Не удалось перевести содержание новости")
        translated.append(ru)

    if len(translated) < 2 or sum(map(len, translated)) < 200:
        raise ValueError("Недостаточно содержания после перевода")
    LOG.info("Редакционная выжимка: %s абзаца из %s", len(translated), article.source)
    return title_ru, "\n\n".join(translated)


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


def complete_sentences_for_budget(text: str, length_budget: int) -> str:
    """Do not truncate a post inside a sentence or source quotation."""
    if len(text) <= length_budget:
        return text.strip()
    result = []
    for block in text.split("\n\n"):
        sentences = split_news_sentences(block)
        for sentence in sentences:
            candidate = "\n\n".join(result + [sentence]) if not result else (
                "\n\n".join(result + [sentence])
            )
            if len(candidate) > length_budget:
                break
            result.append(sentence)
    return " ".join(result).strip()


def format_post(article: Article, title_ru: str, summary_ru: str) -> str:
    emoji = news_emoji(article, title_ru)
    result = f"{emoji} <b>{html.escape(title_ru)}</b>\n\n"
    if summary_ru.strip():
        result += f"{html.escape(summary_ru.strip())}\n\n"
    result += (
        f'🔗 <a href="{html.escape(article.url, quote=True)}">'
        f"Источник: {html.escape(article.source)}</a>"
    )
    return result


def photo_caption(article: Article, title_ru: str, summary_ru: str) -> str:
    """Readable photo post, constrained to Telegram's 1024 visible characters."""
    title = title_ru.strip()
    emoji = news_emoji(article, title_ru)
    start = f"{emoji} <b>{html.escape(title)}</b>\n\n"
    source = (
        f'\n\n🔗 <a href="{html.escape(article.url, quote=True)}">'
        f"Источник: {html.escape(article.source)}</a>"
    )
    # HTML escapes are not visible characters; Telegram limits the decoded text.
    visible_reserve = len(title) + len(article.source) + 38
    budget = max(0, min(770, 1024 - visible_reserve))
    content = summary_ru.strip()
    if len(content) > budget:
        # Never publish a dangling piece of a sentence. If the whole text
        # cannot fit, retain the first complete sentences.
        paragraphs = []
        remaining = budget
        for paragraph in content.split("\n\n"):
            if len(paragraph) <= remaining:
                paragraphs.append(paragraph)
                remaining -= len(paragraph) + 2
                continue
            if not paragraphs:
                clip = complete_sentences_for_budget(paragraph, remaining)
                if clip:
                    paragraphs.append(clip)
            break
        content = "\n\n".join(paragraphs)
    return start + html.escape(content) + source


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


def _telegram_channel_avatar(token: str, channel: str) -> bytes:
    """Use the real Telegram channel logo; no user uploads/hosting required."""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": channel}, timeout=12,
        )
        payload = resp.json()
        if not payload.get("ok"):
            return b""
        photo = payload.get("result", {}).get("photo", {})
        file_id = photo.get("big_file_id") or photo.get("small_file_id")
        if not file_id:
            return b""
        info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id}, timeout=12,
        ).json()
        path = info.get("result", {}).get("file_path", "")
        if not info.get("ok") or not path:
            return b""
        img = requests.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=15)
        img.raise_for_status()
        if len(img.content) > 2_000_000:
            return b""
        return img.content
    except (requests.RequestException, ValueError, KeyError):
        return b""


def branded_fallback_photo(token: str, channel: str) -> bytes:
    """Landscape 16:9 fallback featuring the actual channel profile logo."""
    w, h = 1200, 675
    im = Image.new("RGB", (w, h), (3, 22, 59))
    px = im.load()
    for y in range(h):
        for x in range(w):
            # Dark broadcast-news blue background, subtle luminous center.
            dx, dy = (x - w / 2) / w, (y - h / 2) / h
            glow = max(0, int(35 * (1 - (dx * dx * 3 + dy * dy * 2))))
            px[x, y] = (4 + glow // 8, 20 + glow, 57 + glow * 2)
    draw = ImageDraw.Draw(im)
    for width, y, color in (
        (38, 37, (190, 18, 41)), (18, 75, (29, 90, 184)),
        (25, 615, (230, 237, 248)), (29, 648, (191, 26, 42)),
    ):
        draw.line([(0, y + 42), (w, y - 38)], fill=color, width=width)
    for radius in (220, 270):
        x0, y0 = w // 2 - radius, 310 - radius
        draw.ellipse([x0, y0, x0 + radius * 2, y0 + radius * 2],
                     outline=(27, 87, 160), width=3)
    draw.ellipse((415, 122, 785, 492), fill=(13, 42, 93), outline=(229, 232, 242), width=11)
    draw.arc((412, 119, 788, 495), 185, 360, fill=(215, 30, 44), width=15)
    draw.arc((412, 119, 788, 495), 0, 170, fill=(45, 110, 221), width=13)
    avatar = _telegram_channel_avatar(token, channel)
    if avatar:
        try:
            with Image.open(BytesIO(avatar)) as picture:
                portrait = ImageOps.fit(picture.convert("RGB"), (328, 328), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", (328, 328), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 327, 327), fill=255)
            im.paste(portrait, (436, 143), mask)
        except (OSError, ValueError):
            LOG.warning("Аватарку Telegram не удалось открыть; используем текстовый логотип")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 88)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(im)
    word = "Сербия 24"
    box = draw.textbbox((0, 0), word, font=font, stroke_width=1)
    tw = box[2] - box[0]
    text_x = (w - tw) / 2
    draw.rounded_rectangle(
        (max(40, text_x - 35), 502, min(w - 40, text_x + tw + 35), 619),
        radius=20, fill=(151, 19, 37), outline=(238, 242, 250), width=4,
    )
    draw.text((text_x, 510), word, fill=(255, 255, 255), font=font,
              stroke_width=2, stroke_fill=(8, 22, 54))
    out = BytesIO()
    im.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def send_branded_fallback(token: str, channel: str, caption: str) -> None:
    """Never publish a text-only item if the user requested photo-only posts."""
    image = branded_fallback_photo(token, channel)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": channel, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("serbia24.jpg", BytesIO(image), "image/jpeg")},
            timeout=35,
        )
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("Не получилось отправить резервное фото в Telegram") from None
    if not payload.get("ok") or response.status_code != 200:
        raise RuntimeError("Telegram не принял резервное фото; новость пропущена")


def post_telegram(
    message: str,
    token: str,
    channel: str,
    preview_url: str = "",
    photo_url: str = "",
    caption: str = "",
) -> bool:
    """Send real article picture or branded fallback, NEVER plain text."""
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
        LOG.warning("Источник не дал отправить фото (%s); используем логотип", error)
    send_branded_fallback(token, channel, caption or message)
    LOG.info("Опубликована новость с резервным логотипом канала")
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

    all_articles = fetch_news()
    # A feed using the very same picture for different articles is likely
    # providing a generic promo/placeholder (such as a Danas interview).
    image_counts = Counter(a.image_url for a in all_articles if a.image_url)
    generic_images = {url for url, count in image_counts.items() if count > 1}
    if generic_images:
        LOG.info("Скрываем %s повторяющихся шаблонных изображений RSS", len(generic_images))
    candidates = [a for a in all_articles if recent_enough(a, now) and relevant(a)]
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
                if article.image_url and article.image_url in generic_images:
                    LOG.info("Шаблонное фото на нескольких новостях — публикуем без него: %s", article.source)
                    image_url = ""
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
