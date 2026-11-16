"""Diagnostic only: never sends Telegram messages or changes publication history."""
import collections
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests
import bot

def main():
    state = bot.read_state()
    print("CURRENT_UTC", datetime.now(timezone.utc).isoformat())
    print("LAST_SENT", state.get("last_sent"), "POST_COUNT", len(state.get("posted", {})))
    counts = collections.Counter()
    qualifying = []
    for source, url in bot.FEEDS:
        try:
            r = bot.HTTP.get(url, timeout=22)
            print("FEED_HTTP", source, r.status_code, "bytes", len(r.content),
                  "content_type", r.headers.get("content-type", "")[:60])
            if r.status_code != 200:
                continue
            entries = feedparser.parse(r.content).entries
            print("FEED_ENTRIES", source, len(entries))
            for ent in entries[:30]:
                title = bot.clean(ent.get("title", ""))
                summary = bot.clean(ent.get("summary", "") or ent.get("description", ""))
                link = ent.get("link", "").split("#")[0]
                counts["total"] += 1
                if len(title) < 22:
                    counts["short_title"] += 1
                    continue
                if len(summary) < 95:
                    counts["short_summary"] += 1
                    continue
                if urlparse(link).scheme != "https":
                    counts["not_https"] += 1
                    continue
                if any(term in title.lower() for term in bot.MEDICAL_RISK):
                    counts["medical_filtered"] += 1
                    continue
                topic = bot.story_topics(title)
                if not topic:
                    counts["no_topic"] += 1
                    continue
                counts["eligible"] += 1
                qualifying.append((source, title, topic[1], summary))
        except (requests.RequestException, ValueError) as err:
            print("FEED_EXCEPTION", source, type(err).__name__)
    print("FILTER_TOTALS", dict(counts))
    print("ELIGIBLE_SAMPLE_COUNT", len(qualifying))
    for source,title,topic,summary in qualifying[:6]:
        print("CANDIDATE", source, "topic=",topic,"title=",repr(title[:120]))
    if qualifying:
        print("TEST_COMMONS_TOPIC", qualifying[0][2])
        img=bot.commons_image(qualifying[0][2],state)
        print("COMMONS_OK", bool(img), "image_id",img.get("id") if img else None)
        tr=bot.translate(qualifying[0][1])
        print("TRANSLATION_OK", bool(tr), "preview",repr(tr[:100]))
    else:
        print("NO_ELIGIBLE_RSS_ITEMS; no media/translation test")
    try:
        nasa = bot.nasa_candidates(state, datetime.now(timezone.utc))
        print("NASA_CANDIDATES",len(nasa))
        if nasa:
            video = bot.nasa_mp4(nasa[0]["id"])
            print("NASA_MP4_OK",bool(video))
    except Exception as err:
        print("NASA_ERROR",type(err).__name__,str(err)[:150])

if __name__=="__main__":
    main()
