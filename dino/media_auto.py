"""Automatically discover reusable themed photos, GIFs and videos.

The bot uploads media into Telegram. No TikTok/YouTube scraping or unlicensed
reposting. Credits are displayed for CC BY/CC BY-SA works.
"""
from __future__ import annotations

import html
import io
import random
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageOps

import bot

# Do not describe stock footage as a news recording or as an actual event.
QUERIES = {
    "video": [
        ("dinosaur animation", "анимация про динозавров"),
        ("dinosaur costume", "динозавры в костюмах"),
        ("inflatable dinosaur", "забавные динозавры"),
        ("dinosaur stop motion", "динозавры в стоп-моушен"),
        ("dinosaur dance", "танцующие динозавры"),
        ("animal mask cosplay", "необычные маски"),
        ("fursuit dance", "костюмы и танцы"),
        ("therian costume", "тематические костюмы"),
    ],
    "gif": [
        ("dinosaur animation", "динозавры"),
        ("dinosaur dance", "динозавры"),
        ("dino cartoon", "мультяшные динозавры"),
        ("dinosaur meme", "смешные динозавры"),
        ("animal mask", "маски животных"),
        ("dinosaur", "динозавры"),
    ],
    "photo": [
        ("therian mask", "маски терриан"),
        ("animal mask cosplay", "маски животных"),
        ("dinosaur costume", "костюмы динозавров"),
        ("inflatable dinosaur costume", "надувные диносьюты"),
        ("dinosaur suit", "диносьюты"),
        ("fursuit costume", "костюмы животных"),
        ("animal costume", "костюмы животных"),
        ("quadrobics", "квадробика"),
    ],
}
SKIP_NAMES = (
    "blood", "death", "murder", "kill", "injured", "assault", "sexual",
    "nsfw", "nude", "child", "children", "school", "kid", "little girl",
    "little boy", "bully", "victim", "harassment", "violence", "war",
)
SUPPORTED = {
    "photo": ("image/jpeg", "image/png", "image/webp"),
    "gif": ("image/gif",),
    "video": ("video/webm", "video/ogg", "video/mp4", "application/ogg"),
}
# Limit over-fetching and avoid downloads larger than Telegram accepts.
MAX_BYTES = {"photo": 15_000_000, "gif": 16_000_000, "video": 28_000_000}
HEADLINES = {
    "video": "🎬 ВИДЕО",
    "gif": "😂 GIF ДНЯ",
    "photo": "📸 ФОТО",
}
QUESTIONS = {
    "video": ["Как вам такой ролик? 🦖", "Кто тоже любит такие костюмы? 🐾", "Оцените от 1 до 10! 🔥"],
    "gif": ["Сколько раз пересмотрели? 😂", "Настроение на сегодня? 🐉", "Кому отправим? 🦖"],
    "photo": ["Как вам этот образ? 🐾", "Какой костюм круче? 🦖", "Хотели бы такой? 👀"],
}


def strip_html(value):
    value = re.sub(r"<[^>]*>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def license_data(metadata):
    short = strip_html(metadata.get("LicenseShortName", {}).get("value", ""))
    low = short.lower()
    license_url = strip_html(metadata.get("LicenseUrl", {}).get("value", ""))
    if "cc0" in low or "public domain" in low:
        return {"name": short, "credit": "", "license_url": license_url}
    if not re.match(r"^cc by(?:-sa)?[ -]\d", low):
        return None
    artist = strip_html(metadata.get("Artist", {}).get("value", ""))
    artist = re.sub(r"https?://\S+", "", artist).strip()
    if not artist or len(artist) > 90:
        return None
    if not license_url.startswith("https://creativecommons.org/licenses/"):
        return None
    return {"name": short, "credit": artist, "license_url": license_url}


def type_matches(item, kind):
    mime = item.get("mime", "").lower()
    url = item.get("url", "").lower().split("?")[0]
    if kind == "gif":
        return mime == "image/gif" or url.endswith(".gif")
    if kind == "video":
        return mime.startswith("video/") or (
            mime == "application/ogg" and url.endswith((".ogv", ".ogg"))
        )
    return mime in SUPPORTED["photo"]


def parse_hits(data, kind, topic):
    pages = data.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    results = []
    for page in pages:
        title = page.get("title", "")
        lower_title = title.lower()
        if "naughty_dino_gets_a_surprise" in lower_title.replace(" ", "_"):
            continue  # Already posted by the first-video workflow.
        if any(term in lower_title for term in SKIP_NAMES):
            continue
        imageinfo = page.get("imageinfo") or []
        if not imageinfo:
            continue
        info = imageinfo[0]
        source = info.get("url", "")
        if not source.startswith("https://") or not type_matches(info, kind):
            continue
        size = int(info.get("size", 0) or 0)
        if not (512 <= size <= MAX_BYTES[kind]):
            continue
        rights = license_data(info.get("extmetadata", {}))
        if rights is None:
            continue
        results.append({
            "id": "commons:" + str(page.get("pageid", title)),
            "kind": kind,
            "title": title.removeprefix("File:"),
            "topic": topic,
            "url": source,
            "size": size,
            "description_url": info.get("descriptionurl", "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"))),
            "rights": rights,
        })
    return results


def query_commons(term, topic, kind):
    # Search in File namespace, filter by MIME. Search syntax provides a hint
    # rather than assuming all returned pages have the requested media type.
    suffix = {
        "gif": "filemime:image/gif",
        "video": "filetype:video",
        "photo": "filetype:bitmap",
    }[kind]
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "generator": "search",
        "gsrsearch": term + " " + suffix,
        "gsrnamespace": 6,
        "gsrlimit": 30,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    try:
        response = bot.HTTP.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params, timeout=22,
        )
        response.raise_for_status()
        return parse_hits(response.json(), kind, topic)
    except (requests.RequestException, ValueError, KeyError) as exc:
        print("MEDIA_SOURCE_UNAVAILABLE", kind, type(exc).__name__)
        return []


def candidates(state, kind, now):
    cache = state.setdefault("media_cache", {})
    cached = cache.get(kind, {})
    if cached.get("at", 0) > time.time() - 3600:
        return cached.get("items", [])
    terms = QUERIES[kind]
    slot = (now.timetuple().tm_yday * 7 + now.hour * 4 + now.minute // 15)
    start = slot % len(terms)
    hits = []
    # Two different searches per fresh cache; switch queries every hour.
    for i in range(2):
        term, topic = terms[(start + i) % len(terms)]
        hits.extend(query_commons(term, topic, kind))
    unique = {hit["id"]: hit for hit in hits}
    results = list(unique.values())
    random.Random(slot).shuffle(results)
    cache[kind] = {"at": time.time(), "items": results[:70]}
    print("MEDIA_DISCOVERY", kind, "matching_reusable", len(results))
    return results


def choose(state, kind, now):
    used = set(state.setdefault("used_media", []))
    hits = candidates(state, kind, now)
    for hit in hits:
        if hit["id"] not in used:
            return hit
    return None


def retrieve(url, max_size):
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS media URLs permitted")
    with bot.HTTP.get(url, stream=True, timeout=50) as resp:
        resp.raise_for_status()
        announced = int(resp.headers.get("content-length", "0") or 0)
        if announced > max_size:
            raise ValueError("Too large")
        memory = io.BytesIO()
        for chunk in resp.iter_content(128 * 1024):
            if not chunk:
                continue
            memory.write(chunk)
            if memory.tell() > max_size:
                raise ValueError("Download exceeds size limit")
        return memory.getvalue()


def caption_for(hit, kind):
    topic = html.escape(hit["topic"])
    caption = (HEADLINES[kind] + ": " + topic +
               "\n\n" + random.choice(QUESTIONS[kind]))
    license_info = hit["rights"]
    if license_info["credit"]:
        caption += "\n\nАвтор: " + html.escape(license_info["credit"][:85])
        caption += " · " + html.escape(license_info["name"])
        if license_info["license_url"]:
            caption += ' · <a href="' + html.escape(license_info["license_url"], quote=True) + '">лицензия</a>'
    caption += '\n<a href="' + html.escape(hit["description_url"], quote=True) + '">·</a>'
    if hit["kind"] == "video":
        caption += "\nФрагмент перекодирован для Telegram."
    return caption[:1000]


def render_video(source, dst, gif_style=False):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-t", "6" if gif_style else "15",
        "-vf", "scale=w='min(720,iw)':h=-2:flags=lanczos",
        "-r", "24", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
    ]
    if gif_style:
        cmd.extend(["-an"])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "96k"])
    cmd.extend(["-movflags", "+faststart", str(dst)])
    subprocess.run(cmd, check=True, timeout=100)
    if not dst.exists() or dst.stat().st_size < 1000 or dst.stat().st_size > 47_000_000:
        raise RuntimeError("Transcoded video invalid")


def send_selected(hit, kind, dry_run=False):
    if dry_run:
        print("MEDIA_DRY_RUN", kind, hit["id"], hit["title"][:100])
        return True
    data = retrieve(hit["url"], MAX_BYTES[hit["kind"]])
    caption = caption_for(hit, kind)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        if kind == "photo":
            image = Image.open(io.BytesIO(data))
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600))
            out = p / "photo.jpg"
            image.save(out, "JPEG", quality=88)
            with out.open("rb") as fp:
                result = bot.telegram_send(
                    "sendPhoto",
                    data={"chat_id": bot.CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": ("photo.jpg", fp, "image/jpeg")},
                )
        elif kind == "gif" and hit["kind"] == "gif":
            img = Image.open(io.BytesIO(data))
            if not getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) < 2:
                raise ValueError("Image is not an animated GIF")
            out = p / "animation.gif"
            out.write_bytes(data)
            with out.open("rb") as fp:
                result = bot.telegram_send(
                    "sendAnimation",
                    data={"chat_id": bot.CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                    files={"animation": ("animation.gif", fp, "image/gif")},
                )
        else:
            src = p / "original.webm"
            dst = p / "video.mp4"
            src.write_bytes(data)
            render_video(src, dst, gif_style=(kind == "gif"))
            method = "sendAnimation" if kind == "gif" else "sendVideo"
            field = "animation" if kind == "gif" else "video"
            payload = {"chat_id": bot.CHAT_ID, "caption": caption, "parse_mode": "HTML"}
            if method == "sendVideo":
                payload["supports_streaming"] = "true"
            with dst.open("rb") as fp:
                result = bot.telegram_send(
                    method, data=payload,
                    files={field: ("video.mp4", fp, "video/mp4")},
                )
        message_id = result.get("message_id")
        if not message_id:
            raise RuntimeError("Telegram did not acknowledge the message")
        print("MEDIA_POSTED_OK", kind, hit["id"], "message_id", message_id)
        return True


def publish_media(state, now, kind, dry_run=False):
    hit = choose(state, kind, now)
    # Animate a short freely-licensed movie as a Telegram GIF if no native
    # animated GIF exists. Do not use the same file twice across media types.
    if not hit and kind == "gif":
        hit = choose(state, "video", now)
        if hit:
            print("MEDIA_GIF_FROM_VIDEO", hit["id"])
    if not hit:
        print("MEDIA_NONE", kind)
        return False
    try:
        if not send_selected(hit, kind, dry_run=dry_run):
            return False
    except (requests.RequestException, OSError, ValueError, RuntimeError,
            subprocess.SubprocessError) as exc:
        print("MEDIA_POST_ERROR", kind, type(exc).__name__, str(exc)[:150])
        return False
    if not dry_run:
        state.setdefault("used_media", []).append(hit["id"])
        state["used_media"] = state["used_media"][-1200:]
    return True


def main_media(state, now, dry_run=False):
    # ~60% videos/GIFs, ~40% photos; news comes from bot.py on every fifth slot.
    slots = ("video", "photo", "gif", "video", "photo", "video", "gif", "photo")
    slot = now.hour * 4 + now.minute // 15
    initial = slots[slot % len(slots)]
    kinds = [initial] + [k for k in ("video", "gif", "photo") if k != initial]
    for kind in kinds:
        if publish_media(state, now, kind, dry_run=dry_run):
            return kind
    return None
