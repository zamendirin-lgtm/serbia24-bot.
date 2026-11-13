"""DinoDvij: auto-publish relevant videos only, in Telegram-native 9:16 MP4."""
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
    if not re.fullmatch(r"cc by(?:-sa)?[ -]?[1-4]\.0", low):
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


def query_catalog(query):
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrnamespace": "6",
        "gsrsearch": query + " filetype:video", "gsrlimit": "40",
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata"
    }
    try:
        response = bot.HTTP.get(BASE, params=params, timeout=18)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError, KeyError) as exc:
        print("VIDEO_SEARCH_UNAVAILABLE", type(exc).__name__)
        return []
    hits = []
    for page in pages if isinstance(pages, list) else pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = (info.get("mime") or "").lower()
        if not mime.startswith("video/") and mime != "application/ogg":
            continue
        size = int(info.get("size") or 0)
        if size < 40_000 or size > MAX_DOWNLOAD:
            continue
        url = info.get("url", "")
        if not media_url_allowed(url):
            continue
        title = page.get("title", "")
        meta = info.get("extmetadata", {})
        description = meta.get("ImageDescription", {}).get("value", "")
        if not appropriate(title, description):
            continue
        rights = permitted_license(meta)
        if not rights:
            continue
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        hits.append({
            "id": "commons-video:" + str(page.get("pageid")),
            "title": title,
            "url": url,
            "page_url": info.get("descriptionurl", ""),
            "width": width,
            "height": height,
            "size": size,
            "rights": rights
        })
    return hits


def lookup_candidates(state, now):
    cache = state.setdefault("video_search_cache", {})
    cycle = now.timetuple().tm_yday * 96 + now.hour * 4 + now.minute // 15
    if cache.get("cycle") == cycle:
        return cache.get("hits", [])
    # Rotate queries each time; no dependency on paid/API-key integrations.
    start = cycle % len(QUERIES)
    terms = [QUERIES[(start + i) % len(QUERIES)] for i in range(3)]
    candidates = {}
    for term in terms:
        for hit in query_catalog(term):
            candidates[hit["id"]] = hit
    hits = list(candidates.values())
    # Portrait / near-9:16 is first choice; landscape is allowed only when
    # the video is relevant, and the output itself is always 9:16.
    def score(hit):
        w, h = hit["width"], hit["height"]
        ratio = w / h if w and h else 1.777
        return (
            (4 if h > w else 0)
            + (2 if 0.45 <= ratio <= 0.75 else 0)
            - abs(ratio - 9 / 16),
            int("therian" in hit["title"].lower() or "dinosuit" in hit["title"].lower())
        )
    hits.sort(key=score, reverse=True)
    cache.clear()
    # Cache results for this execution to avoid repeating searches within run.
    cache.update({"cycle": cycle, "hits": hits[:80]})
    print("RELEVANT_VIDEO_CANDIDATES", len(hits))
    for candidate in hits[:5]:
        print("VIDEO_CHOICE", candidate["title"][:95], candidate["width"], candidate["height"])
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


def to_vertical(source, dest):
    # Preserve the whole source frame; blur the margins when original footage
    # is not portrait. Result is 720x1280 (9:16) for Telegram playback.
    filter_graph = (
        "[0:v]split=2[base][fg];"
        "[base]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,boxblur=12:2[blur];"
        "[fg]scale=720:1280:force_original_aspect_ratio=decrease[front];"
        "[blur][front]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-t", str(MAX_SECONDS), "-filter_complex", filter_graph,
        "-map", "[v]", "-map", "0:a:0?", "-r", "24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(dest)
    ]
    subprocess.run(cmd, check=True, timeout=120)
    size = dest.stat().st_size
    if size < 2000 or size > 48_000_000:
        raise RuntimeError("Invalid Telegram MP4 file")


def minimal_caption(hit):
    # Users asked for video only: no headlines, questions or descriptions.
    # CC0 / public domain = no caption; CC BY / BY-SA = mandatory attribution.
    rights = hit["rights"]
    if not rights["author"]:
        return None
    source_url = hit.get("page_url", "")
    if not media_url_allowed(source_url):
        source_url = "https://commons.wikimedia.org/"
    return (
        "Видео: " + html.escape(rights["author"]) +
        " · " + html.escape(rights["label"]) +
        ' · <a href="' + html.escape(rights["url"], quote=True) + '">лицензия</a>' +
        ' · <a href="' + html.escape(source_url, quote=True) + '">·</a>' +
        "\nФормат адаптирован: 9:16."
    )


def post_hit(hit, dry_run=False):
    print("SELECTED_VIDEO", hit["title"][:110], "portrait", hit["height"] > hit["width"])
    if dry_run:
        print("VIDEO_DRY_RUN_OK")
        return True
    source_bytes = download_limited(hit["url"])
    with tempfile.TemporaryDirectory(prefix="dinovideo-") as tmp:
        original = Path(tmp) / "source.webm"
        mp4 = Path(tmp) / "vertical.mp4"
        original.write_bytes(source_bytes)
        to_vertical(original, mp4)
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
        print("VIDEO_POSTED_OK", response["message_id"], "format 720x1280")
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
