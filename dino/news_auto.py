"""Verified-interest news for therians, quadrobics and dinosaur costumes.

Publish factual short summaries in Russian with a source link and a real
licensed illustrative photo. No fabricated breaking news, empty headlines,
random VS graphics, or automatic translation hallucinations.
"""
from __future__ import annotations

import html
import io
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from PIL import Image, ImageOps

import bot

# These were individually checked against real articles in November 2026.
# They are labelled "Интересное" or "Разбор", NOT breaking news.
CURATED = [
    {
        "key": "canal10-2026-10-16-quadrobics",
        "published": "2026-10-16",
        "title": "Почему квадробика снова вызывает споры в интернете",
        "summary": "16 октября издание Canal 10 рассказало о популярности териан и квадробики в TikTok и Instagram. В материале также обсуждаются нагрузки на запястья и спину при прыжках на четвереньках. А вы считаете квадробику спортом или интернет-трендом?",
        "url": "https://www.canal10.com.ni/noticia/therians-que-hay-detras-de-la-tendencia-viral-que-domina-tiktok-y-redes-sociales/",
        "search": "quadrobics animal mask",
        "type": "Разбор · 16 октября 2026",
    },
    {
        "key": "tovima-2026-05-21-therians",
        "published": "2026-05-21",
        "title": "Терианы: самовыражение или тренд, раздутый соцсетями?",
        "summary": "Издание To Vima описало распространение роликов с масками и движениями животных. Одни участники воспринимают это как часть своей идентичности, другие — как творческое увлечение. Из-за популярности коротких видео об этих различиях часто забывают.",
        "url": "https://www.tovima.com/culture/therians-trend-goes-viral-identity-or-online-myth/amp/",
        "search": "therian animal masks",
        "type": "Интересное · 21 мая 2026",
    },
    {
        "key": "unsw-2025-10-quadrobics",
        "published": "2025-10-01",
        "title": "Квадробика: реально тренировка или просто эффектный контент?",
        "summary": "Специалисты Университета Нового Южного Уэльса разобрали физические нагрузки и обещания пользы от квадробики — движения на четвереньках, популярного в коротких видео. Они предлагают критически оценивать заявления об эффективности такой тренировки.",
        "url": "https://www.unsw.edu.au/newsroom/news/2025/10/experts-unpack-quadrobics-the-fitness-trend-that-claims-leaping-around-on-all-fours-will-make-you-fit",
        "search": "quadrobics",
        "type": "Разбор · октябрь 2025",
    },
]
QUERIES = (
    "терианы маски", "террианы подростки", "квадробика спорт",
    "диносьюты тренд", "костюм динозавра видео",
)
INTEREST = re.compile(
    r"териан|терриан|квадроб|диносьют|диносют|"
    r"therian|quadrob|dinosuit|dinosaur costume", re.I
)
SKIP = re.compile(
    r"изнасил|убийств|умер|избиен|суицид|педофил|"
    r"политическ|выборы|оружие|убь[её]т", re.I
)
COMMONS = "https://commons.wikimedia.org/w/api.php"
GOOD_MIME = {"image/jpeg", "image/png"}
MAX_IMAGE = 12_000_000


def strip_markup(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def relevant_story(title, summary):
    if not title or len(title) < 28 or len(summary) < 90:
        return False
    if not re.search(r"[а-яё]", title, re.I):
        return False
    if not INTEREST.search(title) or SKIP.search(title + " " + summary):
        return False
    return True


def discover_rss(now):
    """Try direct Russian-language Bing News articles with meaningful excerpts."""
    found = []
    queries = [QUERIES[(now.hour + i) % len(QUERIES)] for i in range(3)]
    for query in queries:
        try:
            response = bot.HTTP.get(
                "https://www.bing.com/news/search",
                params={"q": query, "format": "rss", "setlang": "ru-RU"},
                timeout=16,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:30]:
                link = (entry.get("link") or "").strip()
                p = urlparse(link)
                if p.scheme != "https" or not p.hostname or p.hostname.endswith((
                    "bing.com", "google.com", "news.google.com",
                )):
                    continue
                title = strip_markup(entry.get("title", ""))
                summary = strip_markup(entry.get("summary", ""))
                if summary.lower().startswith(title.lower()[:55]):
                    summary = summary[len(title):].lstrip(" .–-:")
                if not relevant_story(title, summary):
                    continue
                published = entry.get("published_parsed")
                if not published:
                    continue
                ts = __import__("calendar").timegm(published)
                if not (time.time() - 35 * 86400 <= ts <= time.time() + 3600):
                    continue
                key = "rss:" + bot.item_key(title)
                date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")
                found.append({
                    "key": key,
                    "title": title[:130],
                    "summary": summary[:450],
                    "url": link,
                    "search": "therian costume" if "териан" in title.lower() else "quadrobics",
                    "type": "Новости · " + date,
                    "published": date,
                })
        except (requests.RequestException, ValueError) as exc:
            print("NEWS_SOURCE_ERROR", type(exc).__name__)
    print("NEWS_RSS_ELIGIBLE", len(found))
    return found


def source_is_valid(url):
    p = urlparse(url)
    return p.scheme == "https" and bool(p.hostname)


def choose_news(state, now):
    sent = set(state.get("posted_news", []))
    for item in discover_rss(now):
        if item["key"] not in sent:
            return item
    # Curated older pieces are *explicitly dated* and published once only.
    for item in CURATED:
        if item["key"] not in sent:
            return item
    print("NO_VERIFIED_UNPOSTED_NEWS")
    return None


def suitable_rights(meta):
    label = strip_markup(meta.get("LicenseShortName", {}).get("value", ""))
    low = label.lower()
    if "cc0" in low or "public domain" in low:
        return {"credit": "", "license": label or "Public domain"}
    if re.fullmatch(r"cc by(?:-sa)?[ -]?[1-4]\.0(?:[ -][a-z]{2})?", low):
        author = strip_markup(meta.get("Artist", {}).get("value", ""))
        author = re.sub(r"https?://\S+", "", author).strip()
        if 3 <= len(author) <= 85:
            return {"credit": author, "license": label}
    return None


def commons_photo(query, state):
    # Allow reuse only under explicit licenses, with credits when required.
    used = set(state.get("used_news_photos", []))
    for term in (query, "animal costume cosplay", "dinosaur costume"):
        try:
            r = bot.HTTP.get(COMMONS, params={
                "action": "query", "format": "json", "formatversion": 2,
                "generator": "search", "gsrsearch": term + " filetype:bitmap",
                "gsrnamespace": 6, "gsrlimit": 30, "prop": "imageinfo",
                "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 1100,
            }, timeout=16)
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", [])
        except (requests.RequestException, ValueError, KeyError) as exc:
            print("NEWS_COMMONS_UNAVAILABLE", type(exc).__name__)
            continue
        for page in pages if isinstance(pages, list) else pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in GOOD_MIME or int(info.get("size") or 0) > 30_000_000:
                continue
            title = page.get("title", "").lower()
            if any(x in title for x in ("cartoon", "drawing", "logo", "icon", "diagram", "poster", "illustration")):
                continue
            rights = suitable_rights(info.get("extmetadata", {}))
            if rights is None:
                continue
            photo_id = str(page.get("pageid"))
            if photo_id in used:
                continue
            url = info.get("thumburl") or info.get("url", "")
            p = urlparse(url)
            if p.scheme != "https" or p.hostname not in ("upload.wikimedia.org", "commons.wikimedia.org"):
                continue
            try:
                imgresponse = bot.HTTP.get(url, timeout=25)
                imgresponse.raise_for_status()
                if not 2000 < len(imgresponse.content) < MAX_IMAGE:
                    continue
                img = Image.open(io.BytesIO(imgresponse.content))
                if img.width < 250 or img.height < 220:
                    continue
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((1280, 1280))
                output = io.BytesIO()
                img.save(output, "JPEG", quality=87)
                print("NEWS_PHOTO_FOUND",photo_id)
                return output.getvalue(), photo_id, rights, info.get("descriptionurl", "")
            except (requests.RequestException, OSError, ValueError):
                continue
    print("NEWS_NO_LICENSED_PHOTO")
    return None


def group_avatar():
    """User-owned group picture as fallback, not a fake article photograph."""
    try:
        chat = bot.telegram_send("getChat", data={"chat_id": bot.CHAT_ID})
        fid = (chat.get("photo") or {}).get("big_file_id")
        if not fid:
            return None
        record = bot.telegram_send("getFile", data={"file_id": fid})
        path = record.get("file_path")
        if not path or ".." in path or path.startswith("/"):
            return None
        url = "https://api.telegram.org/file/bot" + bot.BOT_TOKEN + "/" + path
        response = bot.HTTP.get(url, timeout=25)
        response.raise_for_status()
        if not 2000 < len(response.content) < MAX_IMAGE:
            return None
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        img.thumbnail((1200, 1200))
        dst = io.BytesIO()
        img.save(dst, "JPEG", quality=85)
        return dst.getvalue()
    except (requests.RequestException, RuntimeError, OSError, ValueError):
        print("GROUP_AVATAR_UNAVAILABLE")
        return None


def publish_news(state, now, dry_run=False):
    """One item per run; only after previous article's cooldown."""
    cooldown = 3 * 3600
    if time.time() - float(state.get("news_last_post_at", 0)) < cooldown:
        print("NEWS_COOLDOWN")
        return False
    story = choose_news(state, now)
    if not story or not source_is_valid(story["url"]):
        return False
    # Never pretend older context is today's breaking news.
    cap = ("🦖 <b>" + html.escape(story["title"]) + "</b>\n\n" +
           html.escape(story["summary"]) + "\n\n" +
           "<i>" + html.escape(story["type"]) + "</i> · " +
           '<a href="' + html.escape(story["url"], quote=True) + '">Источник</a>')
    if dry_run:
        print("NEWS_PREVIEW_OK", story["key"], strip_markup(cap)[:170])
        return True
    photo = commons_photo(story["search"], state)
    image, photo_id = None, None
    if photo:
        image, photo_id, rights, page = photo
        # Make it clear that a stock photo isn't a photo from the news.
        credit = "Фотоиллюстрация"
        if rights["credit"] and source_is_valid(page):
            credit += (": " + html.escape(rights["credit"]) + " · " +
                       html.escape(rights["license"]) + " · " +
                       '<a href="' + html.escape(page, quote=True) + '">·</a>')
        cap += "\n" + credit
    else:
        image = group_avatar()
    if not image:
        print("NEWS_SKIPPED_NO_IMAGE")
        return False
    with io.BytesIO(image) as fp:
        fp.name = "news.jpg"
        result = bot.telegram_send("sendPhoto", data={
            "chat_id": bot.CHAT_ID,
            "caption": cap[:1000],
            "parse_mode": "HTML",
            "disable_notification": "true",
        }, files={"photo": ("news.jpg", fp, "image/jpeg")})
    mid = result.get("message_id")
    if not mid:
        raise RuntimeError("Telegram did not confirm news posting")
    state.setdefault("posted_news", []).append(story["key"])
    state["posted_news"] = state["posted_news"][-400:]
    if photo_id:
        state.setdefault("used_news_photos", []).append(photo_id)
        state["used_news_photos"] = state["used_news_photos"][-400:]
    state["news_last_post_at"] = time.time()
    print("NEWS_PUBLISHED_OK", mid, story["key"], "photo", bool(photo_id))
    return True
