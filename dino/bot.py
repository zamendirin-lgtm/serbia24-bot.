#!/usr/bin/env python3
"""DinoDvij: cautious themed-news Telegram publisher (no source links in posts)."""
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import random
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
TZ = ZoneInfo(os.getenv("DINO_TIMEZONE", "Europe/Belgrade"))
MAX_POSTS = max(1, min(50, int(os.getenv("DINO_MAX_DAILY", "50"))))
BOT_TOKEN = os.getenv("DINO_BOT_TOKEN", "")
CHAT_ID = os.getenv("DINO_CHAT_ID", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")
DRY_RUN = os.getenv("DINO_DRY_RUN", "0").lower() in ("1", "true", "yes")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "DinoDvijNewsBot/1.0 (https://t.me/AVQ_GO)"})
SEARCHES = [
    ("ru", "терианы OR террианы when:7d"),
    ("ru", "диносьюты OR диносюты OR динсьюты when:7d"),
    ("ru", "квадроберы OR квадробика when:7d"),
    ("en", "therian trend when:7d"),
    ("en", "dinosuits OR dinosaur costume trend when:7d"),
    ("en", "quadrobics trend when:7d"),
    ("ru", "маски террианов OR костюм динозавра when:7d"),
    ("en", "therian mask cosplay when:7d"),
]
KEYWORDS = ("териан", "терриан", "диносьют", "диносют", "квадроб",
            "therian", "dinosuit", "quadrob", "dinosaur costume",
            "dinosaur suit", "динозавр", "маск", "костюм")
# Prevent public shaming of minors or republishing graphic/harmful content.
BANNED = ("избил", "избиение", "изнасил", "убий", "умер", "суицид", "жертва",
          "жесток", "подростка изб", "докс", "адрес ребенка", "porn", "sexual",
          "murder", "suicide", "assaulted", "graphic", "beaten", "bullied")
QUESTIONS = [
    "А вы что думаете? 🐾", "Кто уже встречал такое? 👀",
    "Обсудим в чате? 🦖", "Как вам этот тренд? 🔥",
    "Хотели бы попробовать? 🐉",
]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def load_state():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", s.lower())).strip()


def item_key(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:24]


def clean_title(title):
    title = re.sub(r"<[^>]+>", "", title or "")
    title = re.sub(r"\s+-\s+[^-]+$", "", title).strip()
    return re.sub(r"\s+", " ", title)[:170]


def eligible(title, published):
    l = title.lower()
    if len(title) < 18 or any(x in l for x in BANNED):
        return False
    if not any(x in l for x in KEYWORDS):
        return False
    if published:
        ts = time.mktime(published)
        # feedparser dates are UTC; time.mktime local is acceptable at day scale
        if ts < time.time() - 8 * 86400 or ts > time.time() + 86400:
            return False
    return True


def discover_news(state, now):
    # Rotate searches to reduce third-party load (2 searches per 15-minute run).
    slot = now.hour * 4 + now.minute // 15
    selected = [SEARCHES[(slot * 2 + i) % len(SEARCHES)] for i in range(2)]
    found = []
    seen = state.setdefault("seen", {})
    for lang, query in selected:
        params = {
            "q": query, "hl": "ru" if lang == "ru" else "en",
            "gl": "RU" if lang == "ru" else "US",
            "ceid": "RU:ru" if lang == "ru" else "US:en",
        }
        try:
            resp = HTTP.get("https://news.google.com/rss/search",
                            params=params, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:35]:
                title = clean_title(entry.get("title", ""))
                if not eligible(title, entry.get("published_parsed")):
                    continue
                key = item_key(title)
                if key in seen:
                    continue
                found.append({"key": key, "title": title,
                              "url": entry.get("link", ""),
                              "published": entry.get("published", "")})
        except (requests.RequestException, ValueError) as exc:
            print("News feed unavailable:", type(exc).__name__)
    # Prefer Russian headlines, then recent items. Keep some variety via shuffle.
    random.shuffle(found)
    return sorted(found, key=lambda e: not bool(re.search(r"[А-Яа-яЁё]", e["title"])))


def commons_results(state, now):
    """Use only explicitly public-domain / CC0 photos from Wikimedia Commons."""
    cache = state.setdefault("commons_cache", {})
    if time.time() - cache.get("saved_at", 0) < 86400:
        return cache.get("hits", [])
    queries = ("dinosaur costume", "dinosaur suit", "animal costume")
    query = queries[now.timetuple().tm_yday % len(queries)]
    params = {
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": "6", "gsrlimit": "20", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "1080",
        "format": "json",
    }
    hits = []
    try:
        resp = HTTP.get("https://commons.wikimedia.org/w/api.php",
                        params=params, timeout=16)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if not ("CC0" in license_name or
                    "public domain" in license_name.lower()):
                continue
            photo = info.get("thumburl") or info.get("url")
            if not photo or not photo.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            hits.append({"id": "commons-" + str(page.get("pageid")),
                         "webformatURL": photo})
        cache.update({"saved_at": time.time(), "hits": hits})
    except (requests.RequestException, ValueError):
        print("Commons photo source unavailable")
    return hits


def pixabay_results(state, kind, now):
    if not PIXABAY_KEY:
        return commons_results(state, now) if kind != "video" else []
    cache = state.setdefault("pixabay_cache", {})
    key = "videos" if kind == "video" else "photos"
    previous = cache.get(key, {})
    if time.time() - previous.get("saved_at", 0) < 86400:
        return previous.get("hits", [])
    query_options = (["dinosaur costume", "dinosaur animation", "dinosaur"]
                     if kind == "video" else
                     ["dinosaur costume", "animal mask", "dinosaur", "fox mask"])
    q = query_options[now.timetuple().tm_yday % len(query_options)]
    endpoint = ("https://pixabay.com/api/videos/" if kind == "video"
                else "https://pixabay.com/api/")
    try:
        params = {"key": PIXABAY_KEY, "q": q, "safesearch": "true",
                  "per_page": 30, "order": "latest"}
        if kind != "video":
            params["image_type"] = "photo"
        resp = HTTP.get(endpoint, params=params, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        cache[key] = {"saved_at": time.time(), "hits": hits[:30], "q": q}
        return hits
    except (requests.RequestException, ValueError):
        print("Media API unavailable for", kind)
        return previous.get("hits", [])


def choose_media(state, kind, now):
    hits = pixabay_results(state, kind, now)
    used = set(state.setdefault("used_media", []))
    for hit in hits:
        media_id = str(hit.get("id", ""))
        if media_id and media_id not in used:
            return hit
    return None


def wrapped(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        proposed = (current + " " + word).strip()
        if draw.textbbox((0, 0), proposed, font=font)[2] <= max_width:
            current = proposed
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:7]


def poster(title, photo_url=None):
    canvas = Image.new("RGB", (1080, 1080), "#151b34")
    if photo_url:
        try:
            raw = HTTP.get(photo_url, timeout=22)
            raw.raise_for_status()
            if len(raw.content) < 12_000_000:
                img = Image.open(io.BytesIO(raw.content)).convert("RGB")
                scale = max(1080 / img.width, 1080 / img.height)
                img = img.resize((int(img.width * scale), int(img.height * scale)))
                x = (img.width - 1080) // 2
                y = (img.height - 1080) // 2
                canvas.paste(img.crop((x, y, x + 1080, y + 1080)))
                shade = Image.new("RGBA", (1080, 1080), (11, 15, 37, 185))
                canvas = Image.alpha_composite(canvas.convert("RGBA"), shade).convert("RGB")
        except (requests.RequestException, OSError):
            pass
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((50, 64, 1030, 170), radius=24, fill="#00cdb2")
    head = ImageFont.truetype(FONT, 38)
    big = ImageFont.truetype(FONT, 61)
    small = ImageFont.truetype(FONT, 33)
    draw.text((86, 97), "THERIANS x DINOSUITS", font=head, fill="#10152d")
    lines = wrapped(draw, title, big, 940)
    y = max(255, 560 - len(lines) * 39)
    for line in lines:
        draw.text((70, y), line, font=big, fill="white",
                  stroke_width=1, stroke_fill="#161a30")
        y += 85
    draw.rounded_rectangle((56, 916, 1024, 1010), radius=19, fill="#202742")
    draw.text((87, 942), "НОВОСТИ  •  ОБСУЖДЕНИЕ В ЧАТЕ", font=small, fill="#b4fdf1")
    if photo_url:
        draw.text((72, 870), "Тематическая иллюстрация", font=small, fill="#e3e4ec")
    out = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    canvas.save(out.name, quality=88)
    return out.name


def telegram_send(method, **kwargs):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Configure DINO_BOT_TOKEN and DINO_CHAT_ID in GitHub Secrets.")
    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/" + method
    response = HTTP.post(url, timeout=80, **kwargs)
    # Never include URLs containing secrets in error output.
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Telegram returned an invalid response")
    if not response.ok or not payload.get("ok"):
        raise RuntimeError("Telegram rejected " + method + ": " +
                           str(payload.get("description", "unknown"))[:180])
    return payload["result"]


def publish_news(item, state, now):
    title = item["title"]
    # The unobtrusive dot is an ordinary clickable article link.
    # For content requiring explicit author attribution, show that instead.
    source = item.get("url", "")
    source_dot = ('\n\n<a href="' + html.escape(source, quote=True) + '">·</a>') if source.startswith(("https://", "http://")) else ""
    caption = "🦖 " + html.escape(title) + "\n\n" + html.escape(random.choice(QUESTIONS)) + source_dot
    media = choose_media(state, "photo", now)
    path = poster(title, media.get("webformatURL") if media else None)
    try:
        if DRY_RUN:
            print("PREVIEW NEWS:", caption)
        else:
            with open(path, "rb") as f:
                telegram_send("sendPhoto", data={"chat_id": CHAT_ID, "caption": caption[:1000], "parse_mode": "HTML"},
                              files={"photo": ("news.jpg", f, "image/jpeg")})
            if media:
                state.setdefault("used_media", []).append(str(media["id"]))
    finally:
        Path(path).unlink(missing_ok=True)


def make_video(hit):
    # Pixabay content is adapted with a branded overlay, not redistributed standalone.
    variants = hit.get("videos", {})
    variant = next((variants[k] for k in ("tiny", "small", "medium")
                    if variants.get(k, {}).get("url") and
                    variants[k].get("size", 100_000_000) < 23_000_000), None)
    if not variant:
        return None
    raw = HTTP.get(variant["url"], timeout=40)
    raw.raise_for_status()
    if len(raw.content) > 23_000_000:
        return None
    original = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    result = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    original.write(raw.content)
    original.close()
    result.close()
    try:
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-y", "-i", original.name,
            "-t", "13", "-vf",
            "scale=720:-2,drawbox=x=0:y=0:w=iw:h=85:color=black@0.6:t=fill,"
            "drawtext=fontfile=" + FONT + ":text='DINODVIJ VIDEO':"
            "fontcolor=white:fontsize=32:x=(w-text_w)/2:y=22",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            result.name
        ], timeout=90, check=True)
        if Path(result.name).stat().st_size > 45_000_000:
            return None
        return result.name
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        Path(original.name).unlink(missing_ok=True)


def publish_video(hit):
    caption = "🎬 Дино-видео для настроения!\n\nКак вам такой образ? 🦖🐾"
    path = make_video(hit)
    if not path:
        return False
    try:
        if DRY_RUN:
            print("PREVIEW VIDEO:", caption)
        else:
            with open(path, "rb") as f:
                telegram_send("sendVideo", data={"chat_id": CHAT_ID, "caption": caption},
                              files={"video": ("dino.mp4", f, "video/mp4")})
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def telegram_group_candidates():
    """Expose group chat IDs only; never expose messages or user identities."""
    try:
        events = telegram_send("getUpdates", data={"limit": 100, "timeout": 0})
    except (RuntimeError, requests.RequestException):
        print("GROUP_DISCOVERY: unavailable; send /start in the Telegram group")
        return
    found = {}
    for event in events:
        for event_name in ("message", "my_chat_member", "chat_member", "channel_post"):
            obj = event.get(event_name, {})
            chat = obj.get("chat", {}) if isinstance(obj, dict) else {}
            if chat.get("type") in ("group", "supergroup"):
                found[chat.get("id")] = chat.get("title", "")[:80]
    if found:
        for group_id, title in found.items():
            print("GROUP_CANDIDATE:", group_id, "title:", title)
    else:
        print("GROUP_DISCOVERY: no group events visible; send /start@DinoDvij_bot in the group")


def verify_config():
    """Diagnostics: report only booleans and harmless Telegram metadata."""
    print("SECRET_PRESENT DINO_BOT_TOKEN:", bool(BOT_TOKEN))
    print("SECRET_PRESENT DINO_CHAT_ID:", bool(CHAT_ID))
    print("SECRET_PRESENT PIXABAY_API_KEY:", bool(PIXABAY_KEY))
    if not BOT_TOKEN or not CHAT_ID:
        print("CONFIG_CHECK: FAIL - missing Telegram secret(s)")
        return
    try:
        me = telegram_send("getMe")
        chat = telegram_send("getChat", data={"chat_id": CHAT_ID})
        print("CONFIG_CHECK: OK; bot_username:", me.get("username", "unknown"))
        print("CHAT_CHECK: OK; type:", chat.get("type", "unknown"))
        if chat.get("type") not in ("group", "supergroup"):
            print("CHAT_CHECK: INVALID TARGET — expected group or supergroup")
            telegram_group_candidates()
            return
        try:
            member = telegram_send("getChatMember", data={
                "chat_id": CHAT_ID, "user_id": me["id"]
            })
            print("CHAT_MEMBERSHIP:", member.get("status", "unknown"))
        except (RuntimeError, requests.RequestException):
            print("CHAT_MEMBERSHIP: unknown")
    except (RuntimeError, requests.RequestException) as exc:
        print("CONFIG_CHECK: FAIL:", type(exc).__name__,
              str(exc)[:180])


def main():
    if os.getenv("DINO_VERIFY_ONLY", "false").lower() == "true":
        verify_config()
        return
    now = datetime.now(TZ)
    if not 8 <= now.hour < 24:
        print("Quiet hours in", TZ, now.isoformat())
        return
    state = load_state()
    day = now.date().isoformat()
    if state.get("date") != day:
        state["date"] = day
        state["daily_count"] = 0
    # Limit state history and prevent accidental huge git diffs.
    state["seen"] = {k: v for k, v in state.get("seen", {}).items()
                     if isinstance(v, (int, float)) and v > time.time() - 40 * 86400}
    state["used_media"] = state.get("used_media", [])[-700:]
    count = state.get("daily_count", 0)
    if count >= MAX_POSTS:
        print("Daily limit reached", count)
        return
    if not DRY_RUN and (not BOT_TOKEN or not CHAT_ID):
        missing = []
        if not BOT_TOKEN:
            missing.append("DINO_BOT_TOKEN")
        if not CHAT_ID:
            missing.append("DINO_CHAT_ID")
        print("Missing GitHub Secrets (names only):", ", ".join(missing))
        return
    # Never deliver to a private DM; diagnostics can search without a bot token.
    if not DRY_RUN:
        try:
            target = telegram_send("getChat", data={"chat_id": CHAT_ID})
            if target.get("type") not in ("group", "supergroup"):
                print("POST_BLOCKED: DINO_CHAT_ID does not identify a Telegram group")
                return
        except (RuntimeError, requests.RequestException) as exc:
            print("POST_BLOCKED: cannot verify Telegram destination:", type(exc).__name__)
            return
    from memes import scheduled_meme
    from video_only import publish_video_only
    # Original meme battlegrounds and humorous youth posts run in a few
    # dedicated slots. Other checks look for licensed in-chat videos.
    if scheduled_meme(state, now, dry_run=DRY_RUN):
        if not DRY_RUN:
            state["daily_count"] = count + 1
            save_state(state)
        print("MEME_CYCLE_COMPLETE")
        return
    if publish_video_only(state, now, dry_run=DRY_RUN):
        if not DRY_RUN:
            state["daily_count"] = count + 1
        print("VIDEO_CYCLE_COMPLETE")
    if not DRY_RUN:
        save_state(state)


if __name__ == "__main__":
    main()
