"""DinoDvij: auto-publish relevant videos as Telegram MP4, original aspect."""
from __future__ import annotations

import html
import io
import random
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

import bot

# These searches are limited to real costumes and the community's activities,
# not general dinosaur cartoons, wildlife, films or news reports.
QUERIES = (
    "inflatable dinosaur costume",
    "dinosaur costume dance",
    "dinosaur suit",
    "dinosuit costume",
    "therian mask cosplay",
    "therian costume",
    "quadrobics",
    "fursuit dance",
    "fursuit costume",
    "animal mask cosplay",
)
ALLOWED_TERMS = (
    "therian", "териан", "терриан", "dinosuit", "dino suit", "quadrob",
    "квадроб", "dinosaur costume", "dinosaur suit", "dinosaur mascot",
    "inflatable dinosaur", "fursuit", "animal mask", "маска животн",
    "костюм динозавра", "диносьют", "диносют",
)
BLOCKED = (
    "stop motion", "stop-motion", "animation", "cartoon", "explain",
    "dinosaur movie", "dinosaur family", "jurassic", "paleontolog",
    "museum", "skeleton", "fossil", "national geographic",
    "blood", "violence", "attack", "assault", "harassment", "bully",
    "school", "minor", "child", "children", "kids", "teen",
    "nude", "sexual", "nsfw", "porn", "naughty_dino_gets",
)
MAX_DOWNLOAD = 28_000_000
MAX_SECONDS = 18
BASE = "https://commons.wikimedia.org/w/api.php"


def plain(raw):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(raw or "")))).strip()


def permitted_license(meta):
    label = plain(meta.get("LicenseShortName", {}).get("value", ""))
    low = label.lower()
    lic_url = plain(meta.get("LicenseUrl", {}).get("value", ""))
    if "cc0" in low or "public domain" in low:
        return {"label": label, "author": "", "url": ""}
    if not re.fullmatch(r"cc by(?:-sa)?[ -]?[1-4]\.0(?:[ -](?:fr|de|it|uk|us))?", low):
        return None
    author = plain(meta.get("Artist", {}).get("value", ""))
    author = re.sub(r"https?://\S+", "", author).strip()
    if len(author) > 90 or not author:
        return None
    if not lic_url.startswith("https://creativecommons.org/licenses/"):
        return None
    return {"label": label, "author": author, "url": lic_url}


def media_url_allowed(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in (
        "upload.wikimedia.org", "commons.wikimedia.org"
    )


def appropriate(title, description):
    title_low = plain(title).lower().replace("_", " ")
    info = (title_low + " " + plain(description).lower())[:1000]
    if any(term in title_low for term in BLOCKED):
        return False
    # The actual file name must be related to the trend; a loose search result
    # with only a dinosaur in the description is not sufficient.
    return any(term in title_low for term in ALLOWED_TERMS)


def video_from_page(page, category=False):
    """Build a licensed video hit, preferring Commons streaming transcodes.

    Some originals are hundreds of MB; the 480p derivative is a real video
    of the same event, often a few MB. Never fake a video from photos.
    """
    info = (page.get("videoinfo") or [{}])[0]
    mime = (info.get("mime") or "").lower()
    if not mime.startswith("video/") and mime != "application/ogg":
        return None
    title = page.get("title", "")
    if any(term in title.lower().replace("_", " ") for term in BLOCKED):
        return None
    if "TITANIA - Fursuit Etiquette" in title:
        return None  # Animated instructional clip, not community event footage.
    description = info.get("extmetadata", {}).get("ImageDescription", {}).get("value", "")
    if not category and not appropriate(title, description):
        return None
    rights = permitted_license(info.get("extmetadata", {}))
    if not rights:
        return None
    original = info.get("url", "")
    if not media_url_allowed(original):
        return None

    derivative = None
    # MediaWiki TimedMediaHandler returns actual video source URLs.
    # 480p VP9 is usually 2-15 MB even for enormous originals.
    variants = []
    for item in info.get("derivatives", []):
        url = item.get("src") or item.get("url") or ""
        if not media_url_allowed(url):
            continue
        if not urlparse(url).path.endswith((".webm", ".mp4", ".ogv", ".mov")):
            continue
        label = (str(item.get("shorttitle") or "") + " " +
                 str(item.get("transcodekey") or "") + " " + url).lower()
        if "480p" in label:
            priority = 0
        elif "360p" in label:
            priority = 1
        elif "720p" in label:
            priority = 2
        elif "240p" in label:
            priority = 3
        else:
            priority = 5
        variants.append((priority, url))
    variants.sort()
    if variants:
        derivative = variants[0][1]

    original_size = int(info.get("size") or 0)
    if original_size < 40_000:
        return None
    if not derivative and original_size > MAX_DOWNLOAD:
        return None

    return {
        "id": "commons-video:" + str(page.get("pageid")),
        "title": title,
        "url": derivative or original,
        "original_url": original,
        "transcoded": bool(derivative),
        "page_url": info.get("descriptionurl", ""),
        "width": int(info.get("width") or 0),
        "height": int(info.get("height") or 0),
        "size": original_size,
        "rights": rights,
    }


def query_catalog(query):
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrnamespace": "6",
        "gsrsearch": query + " filetype:video", "gsrlimit": "40",
        "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives",
    }
    try:
        response = bot.HTTP.get(BASE, params=params, timeout=20)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError, KeyError) as exc:
        print("VIDEO_SEARCH_UNAVAILABLE", type(exc).__name__)
        return []
    hits = [hit for page in (pages if isinstance(pages, list) else pages.values())
            if (hit := video_from_page(page))]
    print("VIDEO_SEARCH_STATS", query, "raw", len(pages), "usable", len(hits))
    return hits


def query_video_category(category):
    """Use Commons curated categories to discover relevant people in costumes."""
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "categorymembers", "gcmtitle": "Category:" + category,
        "gcmtype": "file", "gcmlimit": "100", "gcmnamespace": "6",
        "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives",
    }
    try:
        response = bot.HTTP.get(BASE, params=params, timeout=20)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError, KeyError) as exc:
        print("VIDEO_CATEGORY_UNAVAILABLE", category, type(exc).__name__)
        return []
    hits = [hit for page in (pages if isinstance(pages, list) else pages.values())
            if (hit := video_from_page(page, category=True))]
    print("VIDEO_CATEGORY_STATS", category, "files", len(pages), "usable", len(hits))
    return hits


def lookup_candidates(state, now):
    cache = state.setdefault("video_search_cache", {})
    cycle = now.timetuple().tm_yday * 96 + now.hour * 4 + now.minute // 15
    if cache.get("version") == 2 and cache.get("cycle") == cycle:
        return cache.get("hits", [])
    # Rotate queries each time; no dependency on paid/API-key integrations.
    start = cycle % len(QUERIES)
    terms = [QUERIES[(start + i) % len(QUERIES)] for i in range(3)]
    candidates = {}
    # Category contents are manually thematically curated by Commons editors.
    # File names can be personal names and therefore lack the word 'fursuit'.
    for cat in ("Videos of fursuits", "Tyrannosaurus costumes"):
        for hit in query_video_category(cat):
            candidates[hit["id"]] = hit
    for term in terms:
        for hit in query_catalog(term):
            candidates[hit["id"]] = hit
    hits = list(candidates.values())
    # Prefer portrait / near 9:16; horizontal is welcome and kept horizontal.
    def score(hit):
        w, h = hit["width"], hit["height"]
        ratio = w / h if w and h else 1.777
        return (
            (4 if h > w else 0)
            + (2 if 0.45 <= ratio <= 0.75 else 0)
            - abs(ratio - 9 / 16),
            int("2026" in hit["title"].lower()),
            int("therian" in hit["title"].lower() or "dinosuit" in hit["title"].lower())
        )
    hits.sort(key=lambda h: (score(h), not bool(h['rights']['author'])), reverse=True)
    cache.clear()
    # Cache results for this execution to avoid repeating searches within run.
    cache.update({"version": 2, "cycle": cycle, "hits": hits[:80]})
    print("RELEVANT_VIDEO_CANDIDATES", len(hits))
    for candidate in hits[:5]:
        print("VIDEO_CHOICE", candidate["title"][:95], "stream", candidate["transcoded"], candidate["width"], candidate["height"])
    return hits


def download_limited(url):
    if not media_url_allowed(url):
        raise ValueError("Unapproved media URL")
    with bot.HTTP.get(url, stream=True, timeout=40) as resp:
        resp.raise_for_status()
        if int(resp.headers.get("content-length", "0") or 0) > MAX_DOWNLOAD:
            raise ValueError("Media too large")
        buf = io.BytesIO()
        for chunk in resp.iter_content(256 * 1024):
            buf.write(chunk)
            if buf.tell() > MAX_DOWNLOAD:
                raise ValueError("Media too large")
    return buf.getvalue()


def to_mp4_original_ratio(source, dest):
    """Convert to streamable MP4, without cropping or adding sidebars."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-t", str(MAX_SECONDS),
        # 1280x1280 is only a bounding box; original aspect is preserved.
        "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
        "-map", "0:v:0", "-map", "0:a:0?", "-r", "24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(dest),
    ]
    subprocess.run(cmd, check=True, timeout=120)
    size = dest.stat().st_size
    if size < 2000 or size > 48_000_000:
        raise RuntimeError("Invalid Telegram MP4 file")


def minimal_caption(hit):
    """A short real-video hook plus the smallest legally complete attribution."""
    title = hit.get("title", "").lower()
    if "pyrkon" in title:
        hook = "🦖 Костюмный парад на Pyrkon! Кто бы так вышел на улицу? 😂"
    elif "conga" in title or "närcon" in title:
        hook = "🐾 Когда вся тусовка пошла в танец 😂"
    else:
        hook = "🎬 Смотрите, что попалось в костюмной тусовке 👀"
    rights = hit["rights"]
    if not rights["author"]:
        return hook
    page = hit.get("page_url", "")
    if not media_url_allowed(page):
        page = "https://commons.wikimedia.org/"
    return (
        hook + "\n" +
        '<a href="' + html.escape(page, quote=True) + '">' +
        html.escape(rights["author"][:65]) + '</a> · ' +
        '<a href="' + html.escape(rights["url"], quote=True) + '">' +
        html.escape(rights["label"]) + '</a> · обр.'
    )


def post_hit(hit, dry_run=False):
    print("SELECTED_VIDEO", hit["title"][:110], "portrait", hit["height"] > hit["width"])
    if dry_run:
        print("VIDEO_DRY_RUN_OK")
        return True
    source_bytes = download_limited(hit["url"])
    with tempfile.TemporaryDirectory(prefix="dinovideo-") as tmp:
        original = Path(tmp) / "source.webm"
        mp4 = Path(tmp) / "video.mp4"
        original.write_bytes(source_bytes)
        to_mp4_original_ratio(original, mp4)
        payload = {
            "chat_id": bot.CHAT_ID,
            "supports_streaming": "true",
            "disable_notification": "true",
        }
        caption = minimal_caption(hit)
        if caption:
            payload["caption"] = caption[:1024]
            payload["parse_mode"] = "HTML"
        with mp4.open("rb") as fp:
            response = bot.telegram_send(
                "sendVideo",
                data=payload,
                files={"video": ("dinovideo.mp4", fp, "video/mp4")}
            )
        if not response.get("message_id"):
            raise RuntimeError("Telegram did not confirm upload")
        print("VIDEO_POSTED_OK", response["message_id"], "original aspect retained")
        return True


def publish_video_only(state, now, dry_run=False):
    used = set(state.setdefault("used_media", []))
    seen = set(state.setdefault("rejected_media", []))
    # Stock dinosaur animation already published in another workflow should
    # never be reposted. No news/photos/GIFs in this version.
    for hit in lookup_candidates(state, now):
        key = hit["id"]
        if key in used or key in seen:
            continue
        try:
            if post_hit(hit, dry_run=dry_run):
                if not dry_run:
                    state.setdefault("used_media", []).append(key)
                    state["used_media"] = state["used_media"][-1500:]
                return True
        except (requests.RequestException, RuntimeError, ValueError,
                OSError, subprocess.SubprocessError) as err:
            print("SKIPPED_VIDEO", type(err).__name__, str(err)[:130])
            if not dry_run:
                state.setdefault("rejected_media", []).append(key)
                state["rejected_media"] = state["rejected_media"][-500:]
    print("NO_RELEVANT_REUSABLE_VIDEOS")
    return False
