"""Conservative Wikimedia Commons photo fallback for Serbia 24 Afisha.

Use only images whose file names genuinely identify the performing act or the
same recurring event, and whose metadata confirms free redistribution rights.
Never copy arbitrary search-engine photos or use a generic image as if it
depicted this particular concert. Return no image when confidence is low.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from unidecode import unidecode

API = "https://commons.wikimedia.org/w/api.php"
LICENSES = re.compile(r"^CC BY(?:-SA)? (?:2\.0|2\.5|3\.0|4\.0)$|^CC0(?: 1\.0)?$", re.I)
PD_NAMES = frozenset({"public domain", "public domain mark", "pd-old", "pd-us", "pd-self"})
STOP = frozenset({
    "koncert", "koncertni", "concert", "festival", "fest", "muzika",
    "music", "live", "show", "band", "bend", "grupa", "group",
    "serbia", "srbija", "beograd", "belgrade", "novi", "sad",
    "november", "novembar", "decembar", "december", "godine",
    "ciklus", "projekat", "projekta", "projektn", "event", "events",
    "performans", "nastup", "predstava", "pozoriste", "theatre",
    "umetnost", "sava", "centar", "plava", "dvorana", "plavi",
})


@dataclass(frozen=True)
class LicensedPhoto:
    image_url: str
    file_page: str
    author: str
    license_name: str
    license_url: str
    subject_label: str

    def credit_html(self) -> str:
        """Attribution next to the image with a link to original + licence."""
        src = html.escape(self.file_page, quote=True)
        licence = html.escape(self.license_url, quote=True)
        name = html.escape(self.author)
        label = html.escape(self.subject_label)
        lic_name = html.escape(self.license_name)
        return (
            f'📷 {label}: <a href="{src}">{name}</a>, '
            f'<a href="{licence}">{lic_name}</a>'
        )


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unidecode(value).lower()).strip()


def significant(value: str) -> list[str]:
    """Only the distinct proper subject, not words like 'concert' or 'festival'."""
    return [
        t for t in dict.fromkeys(re.findall(r"[a-z]{4,}", normalize(value)))
        if t not in STOP and not t.startswith("202")
    ][:6]


def named_subject(event) -> str:
    """Extract the event's named artist/project without its generic promo subtitle.

    Keep the artist's complete name; searching the whole concert announcement
    can hide a relevant licensed photo under unrelated words and venue details.
    """
    title = str(event.title).strip()
    quoted = re.search(r'[«“"]([^»”"]{4,65})[»”"]', title)
    if quoted:
        return quoted.group(1).strip()
    # Example: "Jelena Radanovic — Novi show Druzina ljubavi" should search
    # for Jelena Radanovic, not the entire promotional subtitle.
    return re.split(
        r"\s+(?:[|—–]|-(?=\s))\s+"
        r"|\s*:\s*(?=(?:novi|new)\s+(?:show|koncert|concert))",
        title, maxsplit=1, flags=re.IGNORECASE,
    )[0][:85].strip()


def _meta(info: dict, field: str) -> str:
    raw = info.get("extmetadata", {}).get(field, {})
    if not isinstance(raw, dict):
        return ""
    return BeautifulSoup(str(raw.get("value", "")), "html.parser").get_text(" ", strip=True)


def _allowed_licence(name: str, licence_url: str) -> bool:
    lowered = name.strip().lower()
    if not (LICENSES.fullmatch(name.strip()) or lowered in PD_NAMES):
        return False
    p = urlparse(licence_url)
    if p.scheme != "https" or not p.hostname:
        return False
    if LICENSES.fullmatch(name.strip()):
        return p.hostname in ("creativecommons.org", "www.creativecommons.org") and (
            p.path.startswith("/licenses/") or p.path.startswith("/publicdomain/")
        )
    return p.hostname in ("creativecommons.org", "www.creativecommons.org", "commons.wikimedia.org")


def _candidate(page: dict, tokens: list[str], year: int,
               kind: str) -> LicensedPhoto | None:
    title = str(page.get("title", ""))
    if not title.startswith("File:"):
        return None
    file_words = normalize(title[5:])
    count = sum(t in file_words for t in tokens)
    if len(tokens) >= 2:
        if count < 2:
            return None
    elif not tokens or count != 1 or len(tokens[0]) < 5:
        return None

    # A single word such as "Magla" is also an ordinary Serbian noun (fog).
    # Require independent evidence this depicts music, not a foggy landscape.
    if kind in ("artist", "archive") and len(tokens) == 1 and not any(
        hint in file_words for hint in (
            "band", "bend", "grupa", "group", "koncert", "concert",
            "festival", "performance", "nastup", "muzik", "music",
        )
    ):
        return None

    # A venue name that includes a person's name must not match a portrait.
    if kind == "venue" and not any(
        word in file_words for word in (
            "centar", "center", "platz", "dvorana", "hall", "skcns",
            "fabrika", "kulturn", "theatre", "theater", "venue",
            "zgrada", "building", "club", "klub", "dom",
        )
    ):
        return None

    # An event/archive image must say which year's edition it depicts,
    # rather than matching a totally unrelated production of the same name.
    if kind == "archive" and not any(
        str(y) in file_words for y in (year - 1, year - 2, year - 3)
    ):
        return None

    records = page.get("imageinfo") or []
    if not records or not isinstance(records[0], dict):
        return None
    info = records[0]
    if info.get("mime") not in ("image/jpeg", "image/png"):
        return None
    licence = _meta(info, "LicenseShortName")
    licence_url = _meta(info, "LicenseUrl")
    if not _allowed_licence(licence, licence_url):
        return None
    author = _meta(info, "Artist")
    author = re.sub(r"\s+", " ", author).strip()
    if not author or len(author) > 85:
        # Attribution must be meaningful and fit in a Telegram caption.
        return None
    image = str(info.get("thumburl") or info.get("url") or "")
    file_page = str(info.get("descriptionurl") or "")
    img_host = urlparse(image)
    page_host = urlparse(file_page)
    if (
        img_host.scheme != "https"
        or img_host.hostname != "upload.wikimedia.org"
        or page_host.scheme != "https"
        or page_host.hostname != "commons.wikimedia.org"
    ):
        return None
    return LicensedPhoto(
        image_url=image, file_page=file_page, author=author,
        license_name=licence, license_url=licence_url,
        subject_label={
            "artist": "Фото исполнителя",
            "archive": "Архивное фото",
            "venue": "Фото площадки",
        }[kind],
    )


def _lookup(session: requests.Session, subject: str, year: int,
            kind: str) -> LicensedPhoto | None:
    if kind == "venue":
        # Keep distinctive venue words such as Sava/Centar and Dorcol/Platz.
        words = list(dict.fromkeys(re.findall(r"[a-z]{4,}", normalize(subject))))[:6]
    else:
        words = significant(subject)
    if not words:
        return None
    # Use an exactish subject query; require matching filename words below.
    try:
        res = session.get(API, params={
            "action": "query", "format": "json", "formatversion": 2,
            "generator": "search", "gsrsearch": subject,
            "gsrnamespace": 6, "gsrlimit": 8,
            "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1000,
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist",
        }, timeout=14)
        res.raise_for_status()
        pages = res.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None
    if isinstance(pages, dict):
        pages = list(pages.values())
    if not isinstance(pages, list):
        return None
    for page in pages:
        if isinstance(page, dict):
            photo = _candidate(page, words, year, kind)
            if photo:
                return photo
    return None


def find_licensed_photo(session: requests.Session, event) -> LicensedPhoto | None:
    """Use a licensed photo of the actual act or previous edition only.

    An image of the venue building (even a correct one) is not a relevant
    substitute for performer or event imagery. No hit is a normal outcome.
    """
    if not event.title or not isinstance(event.start, datetime):
        return None
    subject = named_subject(event)
    tokens = significant(subject)
    if not tokens:
        return None
    kind = normalize(str(event.category) + " " + event.title)
    context = normalize(event.title + " " + str(getattr(event, "description", "")))
    music_event = any(k in kind for k in (
        "music", "muzik", "koncert", "concert", "band", "bend", "festival",
        "rock", "jazz", "guitar", "pop",
    ))
    # "Gospodja ministarka" can describe different theatre productions
    # performed by unrelated casts. Never label an old theatre production
    # photo as depicting the current concert's musicians.
    clear_performer = re.search(
        r"\b(?:bend|band|grupa|group|orkestar|orchestra|pevac|singer)\b",
        context,
    ) is not None
    generic_production = re.search(
        r"\b(?:projekat|projekt|project|predstava|theatre|theater|festival|"
        r"maraton|ciklus|cycle|production)\b",
        context,
    ) is not None
    musical = music_event and (
        clear_performer or (len(tokens) >= 2 and not generic_production)
    )
    # Performing group's own images may be from any year; do not label them
    # as depicting today's specific performance.
    if musical:
        found = _lookup(session, subject, event.start.year, "artist")
        if found:
            return found
    # Previous editions of this same event can illustrate recurring events.
    # A photo of the building or surrounding street is NOT suitable for a
    # concert announcement, even when correctly labelled "Фото площадки".
    # Leave the post text-only rather than using irrelevant venue photography.
    return _lookup(session, subject, event.start.year, "archive")
