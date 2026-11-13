#!/usr/bin/env python3
"""Reality / Biohacking: verified science stories and occasional NASA clips."""
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
TZ = ZoneInfo("Europe/Belgrade")
TOKEN = os.getenv("REALITY_BOT_TOKEN", "").strip()
CHAT = os.getenv("REALITY_CHAT_ID", "@priroda_realnosti").strip()
DRY = os.getenv("REALITY_DRY_RUN", "false").lower() in ("1", "true", "yes")
MAX_DAILY = 7
GAP_SECONDS = 120 * 60
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "RealityScienceTelegramBot/1.0 (automated RSS curator; contact via Telegram @priroda_realnosti)"})

FEEDS = [
    ("ScienceDaily / Необычное", "https://www.sciencedaily.com/rss/strange_offbeat.xml"),
    ("ScienceDaily / Наука", "https://www.sciencedaily.com/rss/top/science.xml"),
    ("ScienceDaily / Технологии", "https://www.sciencedaily.com/rss/top/technology.xml"),
    ("ScienceDaily / Здоровье", "https://www.sciencedaily.com/rss/top/health.xml"),
    ("Phys.org / Открытия", "https://phys.org/rss-feed/breaking/"),
]
# A generic illustration is allowed ONLY with a truthful "illustration" label.
IMAGE_TOPICS = {
    "space": ("space", "nebula"), "galaxy": ("space", "galaxy"), "star": ("space", "star"),
    "planet": ("space", "planet"), "moon": ("space", "moon"),
    "mars": ("space", "planet mars"), "black hole": ("space", "black hole"),
    "dinosaur": ("fossil", "dinosaur skeleton"), "fossil": ("fossil", "fossil"),
    "archaeolog": ("history", "archaeological excavation"), "ancient": ("history", "ancient ruins"),
    "ocean": ("nature", "ocean"), "deep sea": ("nature", "deep sea"),
    "octopus": ("animals", "octopus"), "shark": ("animals", "shark"),
    "whale": ("animals", "whale"), "bird": ("animals", "bird"),
    "frog": ("animals", "frog"), "insect": ("animals", "insect"),
    "bee": ("animals", "honey bee"), "spider": ("animals", "spider"),
    "tiger": ("animals", "tiger"), "cat": ("animals", "domestic cat"),
    "animal": ("animals", "wildlife"), "wildlife": ("animals", "wildlife"),
    "forest": ("nature", "forest"), "plant": ("nature", "plants"),
    "mushroom": ("nature", "mushroom"), "fung": ("nature", "fungus"),
    "volcano": ("earth", "volcano"), "earthquake": ("earth", "earthquake"),
    "aurora": ("earth", "aurora borealis"), "cloud": ("earth", "clouds"),
    "brain": ("body", "human brain"), "neuron": ("body", "neuron"),
    "sleep": ("body", "sleep"), "heart": ("body", "human heart"),
    "microbe": ("body", "bacteria"), "bacter": ("body", "bacteria"),
    "dna": ("body", "DNA molecule"), "gene": ("body", "DNA"),
    "cell": ("body", "cell biology"), "robot": ("technology", "robot"),
    "quantum": ("technology", "quantum physics"), "computer": ("technology", "computer"),
    "artificial intelligence": ("technology", "robot"),
}
TOPIC_EMOJI = {"space": "🌌", "fossil": "🦕", "history": "🏛",
               "nature": "🌿", "animals": "🐾", "earth": "🌍",
               "body": "🧠", "technology": "🔬"}
INTERESTING = ("discover", "found", "unusual", "strange", "myster", "rare",
               "surprising", "first", "new", "reveal", "secret", "ancient",
               "strange", "brain", "sleep", "longevity", "space", "planet",
               "animal", "dinosaur", "fossil", "robot", "deep sea",
               "scientist", "research", "galaxy", "moon", "quantum")
MEDICAL_RISK = ("cure", "miracle", "treatment", "supplement", "weight loss",
                "cancer therapy", "clinical trial", "patients", "drug",
                "antidepressant", "disease", "vaccine")
VIDEO_SEARCH = ("aurora", "jupiter", "saturn", "nebula", "hubble", "moon", "sun")


def clean(s):
    return re.sub(r"\s+", " ", BeautifulSoup(html.unescape(str(s or "")), "html.parser").get_text(" ", strip=True)).strip()


def key_for(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:22]


def read_state():
    try:
        obj = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except (OSError, ValueError):
        pass
    return {"posted": {}, "last_sent": 0}


def persist(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def allowed_now(state, now):
    local = now.astimezone(TZ)
    if not 8 <= local.hour < 22:
        print("SKIP: quiet hours (08:00-22:00 Belgrade)")
        return False
    sent = state.get("posted", {})
    today = local.date().isoformat()
    today_count = sum(1 for x in sent.values() if x.get("local_day") == today)
    if today_count >= MAX_DAILY:
        print("SKIP: daily cap", today_count)
        return False
    if now.timestamp() - float(state.get("last_sent", 0)) < GAP_SECONDS:
        print("SKIP: two-hour interval")
        return False
    return True


def translate(raw):
    """Unofficial translation endpoint; fail closed rather than publishing English."""
    raw = clean(raw)
    if not raw:
        return ""
    if len(raw) > 680:
        raw = raw[:680].rsplit(" ", 1)[0]
    try:
        resp = HTTP.get("https://translate.googleapis.com/translate_a/single",
                        params={"client": "gtx", "sl": "en", "tl": "ru",
                                "dt": "t", "q": raw}, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        result_text = "".join(chunk[0] for chunk in result[0] if chunk and chunk[0])
        if len(result_text) >= 12 and re.search("[А-Яа-яЁё]", result_text):
            return clean(result_text)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    return ""


def story_topics(title):
    t = title.lower()
    prefixes = {"archaeolog", "fung", "bacter"}
    for word, topic in IMAGE_TOPICS.items():
        pattern = (r"\b" + re.escape(word) + r"[a-z]*\b" if word in prefixes
                   else r"\b" + re.escape(word) + r"(?:s|es)?\b")
        if re.search(pattern, t):
            return topic
    return None


def story_candidates(state, now):
    seen = state.get("posted", {})
    items = {}
    # Rotate the order for variety, without relying on a random fabricated story.
    feeds = FEEDS[:]
    random.Random(now.date().isoformat()).shuffle(feeds)
    for source, url in feeds:
        try:
            response = HTTP.get(url, timeout=18)
            response.raise_for_status()
            entries = feedparser.parse(response.content).entries[:30]
        except (requests.RequestException, ValueError):
            print("RSS_UNAVAILABLE", source)
            continue
        for ent in entries:
            title = clean(ent.get("title", ""))
            summary = clean(ent.get("summary", "") or ent.get("description", ""))
            link = ent.get("link", "").split("#")[0]
            if not title or not summary or len(summary) < 95 or len(title) < 22:
                continue
            if urlparse(link).scheme != "https":
                continue
            low = title.lower()
            if any(term in low for term in MEDICAL_RISK):
                continue
            topic = story_topics(title)
            if not topic:
                continue  # no unrelated picture just to fill a slot
            pub = ent.get("published_parsed") or ent.get("updated_parsed")
            if pub:
                age = now.timestamp() - time.mktime(pub)
                if age < -3600 or age > 8 * 86400:
                    continue
            else:
                age = 8 * 86400
            k = key_for(link)
            if k in seen:
                continue
            topic_key, picture_search = topic
            interest = sum(3 for w in INTERESTING if w in low)
            score = interest + max(0, 8 - age / 86400)
            if source.endswith("Необычное"):
                score += 6
            # RSS summary is never represented as an independently verified study.
            items[k] = {"key": k, "source": source, "title": title,
                        "summary": summary, "url": link, "topic": topic_key,
                        "picture_search": picture_search, "score": score}
    return sorted(items.values(), key=lambda x: x["score"], reverse=True)


def license_info(meta):
    label = clean(meta.get("LicenseShortName", {}).get("value", ""))
    low = label.lower()
    if "cc0" in low or "public domain" in low:
        return {"name": label or "Public domain", "credit": "", "lic_url": ""}
    # Only permit commercial reuse with full attribution; skip share-alike images
    # rather than accidentally missing the extra licensing obligations.
    if not re.fullmatch(r"cc by[ -]?(?:3|4)\.0", low):
        return None
    author = clean(meta.get("Artist", {}).get("value", ""))
    lic_url = clean(meta.get("LicenseUrl", {}).get("value", ""))
    if not author or len(author) > 70 or not lic_url.startswith("https://creativecommons.org/licenses/"):
        return None
    return {"name": label, "credit": author, "lic_url": lic_url}


def commons_image(query, state):
    params = {"action": "query", "format": "json", "formatversion": "2",
              "generator": "search", "gsrnamespace": "6",
              "gsrsearch": query, "gsrlimit": "25",
              "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
              "iiurlwidth": "1280"}
    try:
        response = HTTP.get("https://commons.wikimedia.org/w/api.php",
                            params=params, timeout=20)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
    except (requests.RequestException, ValueError):
        return None
    used = {x.get("image_id") for x in state.get("posted", {}).values()}
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if (info.get("mime") or "").lower() not in ("image/jpeg", "image/png"):
            continue
        image_id = "commons:" + str(page.get("pageid", ""))
        if image_id in used:
            continue
        licence = license_info(info.get("extmetadata") or {})
        src = info.get("thumburl") or info.get("url", "")
        parsed = urlparse(src)
        if not licence or parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
            continue
        return {"id": image_id, "url": src, "page": info.get("descriptionurl", ""),
                "license": licence}
    return None


def telegram(method, data, files=None):
    if DRY:
        print("DRY_RUN", method, "to", CHAT, "preview:", str(data.get("caption") or data.get("text", ""))[:190])
        return {"ok": True, "result": {"message_id": 0}}
    if not TOKEN:
        raise RuntimeError("REALITY_BOT_TOKEN secret is missing")
    r = HTTP.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                  data=data, files=files, timeout=75)
    r.raise_for_status()
    answer = r.json()
    if not answer.get("ok"):
        raise RuntimeError("Telegram declined " + method)
    return answer


def credit_line(media):
    rights = media["license"]
    if not rights["credit"]:
        return 'Иллюстрация: <a href="' + html.escape(media["page"], quote=True) + '">Wikimedia Commons</a> · ' + html.escape(rights["name"])
    return ("Иллюстрация: " + html.escape(rights["credit"]) +
            ' · <a href="' + html.escape(rights["lic_url"], quote=True) + '">' +
            html.escape(rights["name"]) + '</a> · <a href="' +
            html.escape(media["page"], quote=True) + '">файл</a>')


def story_caption(item, media, ru_title, ru_summary):
    emoji = TOPIC_EMOJI.get(item["topic"], "🔬")
    # Keep HTML links intact and mark topic photos as illustrative, not event photos.
    title = html.escape(ru_title.strip(" .!?")[:125])
    label = '<a href="' + html.escape(item["url"], quote=True) + '">' + html.escape(item["source"]) + '</a>'
    head = f"{emoji} <b>{title}</b>\n\n"
    tail = f"\n\nИсточник: {label}\n{credit_line(media)}"
    for limit in range(520, 99, -30):
        intro = html.escape(ru_summary[:limit].rsplit(" ", 1)[0])
        caption = head + intro + tail
        if len(caption) <= 1024:
            return caption
    return ""


def post_story(item, state):
    media = commons_image(item["picture_search"], state)
    if not media:
        print("NO_REUSABLE_TOPIC_IMAGE", item["picture_search"])
        return False
    ru_title = translate(item["title"])
    ru_summary = translate(item["summary"])
    if not ru_title or not ru_summary or len(ru_summary) < 80:
        print("TRANSLATION_UNAVAILABLE", item["source"])
        return False
    caption = story_caption(item, media, ru_title, ru_summary)
    if len(caption) < 100:
        return False
    print("STORY", item["source"], item["title"][:100], "image:", media["id"])
    reply = telegram("sendPhoto", {"chat_id": CHAT, "photo": media["url"],
                                    "caption": caption, "parse_mode": "HTML",
                                    "disable_notification": "true"})
    if not reply.get("ok"):
        return False
    if not DRY:
        record_send(state, item["key"], media["id"])
    return True


def record_send(state, key, media_id):
    now = datetime.now(timezone.utc)
    local_day = now.astimezone(TZ).date().isoformat()
    state.setdefault("posted", {})[key] = {"at": now.timestamp(),
       "local_day": local_day, "image_id": media_id}
    # Keep 90 days of records, enough to prevent near-term repeats.
    state["posted"] = {k: v for k, v in state["posted"].items()
                       if now.timestamp() - v.get("at", 0) < 90 * 86400}
    state["last_sent"] = now.timestamp()
    persist(state)


def nasa_candidates(state, now):
    term = VIDEO_SEARCH[now.timetuple().tm_yday % len(VIDEO_SEARCH)]
    try:
        response = HTTP.get("https://images-api.nasa.gov/search",
            params={"q": term, "media_type": "video", "page_size": 30,
                    "year_start": "2018"}, timeout=24)
        response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])
    except (requests.RequestException, ValueError):
        return []
    sent = state.get("posted", {})
    candidates = []
    for entry in items:
        meta = (entry.get("data") or [{}])[0]
        nasa_id = meta.get("nasa_id", "")
        desc = clean(meta.get("description", ""))
        title = clean(meta.get("title", ""))
        if not nasa_id or len(desc) < 110 or len(title) < 12:
            continue
        if any(w in (title + " " + desc).lower() for w in
               ("copyright", "all rights reserved", "third party", "licensed music")):
            continue
        key = "nasa:" + nasa_id
        if key in sent:
            continue
        candidates.append({"key": key, "id": nasa_id, "title": title,
            "summary": desc[:550], "url": "https://images.nasa.gov/details/" + nasa_id})
    return candidates[:10]


def nasa_mp4(nasa_id):
    try:
        response = HTTP.get("https://images-api.nasa.gov/asset/" + nasa_id, timeout=25)
        response.raise_for_status()
        entries = response.json().get("collection", {}).get("items", [])
    except (requests.RequestException, ValueError):
        return ""
    paths = [x.get("href", "") for x in entries]
    paths = [u for u in paths if u.startswith("https://") and
             urlparse(u).hostname in ("images-assets.nasa.gov", "images.nasa.gov") and
             urlparse(u).path.lower().endswith(".mp4")]
    # Smaller source encodings are usually preferable on a GitHub runner.
    paths.sort(key=lambda u: (0 if "~small" in u or "~mobile" in u else
                              1 if "~medium" in u else 2, len(u)))
    return paths[0] if paths else ""


def fetch_video(url):
    limit = 35_000_000
    data = io.BytesIO()
    with HTTP.get(url, stream=True, timeout=40) as response:
        response.raise_for_status()
        if int(response.headers.get("content-length", "0") or "0") > limit:
            raise ValueError("NASA source too large")
        for chunk in response.iter_content(256 * 1024):
            data.write(chunk)
            if data.tell() > limit:
                raise ValueError("NASA source too large")
    return data.getvalue()


def post_nasa(state, now):
    for item in nasa_candidates(state, now)[:4]:
        media_url = nasa_mp4(item["id"])
        if not media_url:
            continue
        ru_title = translate(item["title"])
        ru_summary = translate(item["summary"][:430])
        if not ru_title or not ru_summary or len(ru_summary) < 70:
            continue
        caption = ("🎬 <b>" + html.escape(ru_title[:115]) + "</b>\n\n" +
                   html.escape(ru_summary[:570]) + '\n\nВидео: <a href="' +
                   html.escape(item["url"], quote=True) + '">NASA</a> · фрагмент до 25 секунд')
        if DRY:
            telegram("sendVideo", {"chat_id": CHAT, "caption": caption})
            return True
        try:
            source = fetch_video(media_url)
            with tempfile.TemporaryDirectory(prefix="reality-nasa-") as tmp:
                inp = Path(tmp) / "original.mp4"
                out = Path(tmp) / "clip.mp4"
                inp.write_bytes(source)
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-y", "-i", str(inp), "-t", "25",
                    "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                    "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "29",
                    "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                    str(out)], check=True, timeout=100)
                if not 5000 < out.stat().st_size < 45_000_000:
                    continue
                with out.open("rb") as fp:
                    telegram("sendVideo", {"chat_id": CHAT, "caption": caption[:1024],
                        "parse_mode": "HTML", "supports_streaming": "true",
                        "disable_notification": "true"},
                        files={"video": ("science.mp4", fp, "video/mp4")})
            record_send(state, item["key"], item["id"])
            print("NASA_VIDEO_POSTED", item["id"])
            return True
        except (requests.RequestException, OSError, subprocess.SubprocessError,
                RuntimeError, ValueError) as exc:
            print("NASA_VIDEO_SKIPPED", type(exc).__name__)
    return False


def main():
    now = datetime.now(timezone.utc)
    state = read_state()
    if not DRY and not TOKEN:
        print("NO_TOKEN: set REALITY_BOT_TOKEN in GitHub Actions Secrets")
        return
    if not allowed_now(state, now) and not DRY:
        return
    if DRY:
        print("DRY_RUN enabled; no Telegram messages or state changes")
    # At most one science video per day, only around midday.
    today = now.astimezone(TZ).date().isoformat()
    has_video_today = any(v.get("local_day") == today and
                          k.startswith("nasa:") for k, v in state.get("posted", {}).items())
    if not has_video_today and 11 <= now.astimezone(TZ).hour < 19:
        if post_nasa(state, now):
            return
    for item in story_candidates(state, now)[:15]:
        try:
            if post_story(item, state):
                return
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            print("STORY_SKIPPED", type(exc).__name__)
    print("NO_VERIFIABLE_USABLE_MATERIAL; nothing posted")


if __name__ == "__main__":
    main()
