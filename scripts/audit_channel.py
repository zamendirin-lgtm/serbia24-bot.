"""Audit public Telegram Serbia24 news posts without bot credentials.

Read-only scraper of Telegram's public channel preview. It records the
post text as published, with message id and link. If Telegram blocks the
public preview, report that limitation instead of inventing coverage.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import html
import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

CHANNEL = "serbia24live"
BASE_URL = f"https://t.me/s/{CHANNEL}"
RESULT_PATH = Path("reports/serbia24_published_posts.json")


def get_posts(html_doc: str) -> list[dict]:
    soup = BeautifulSoup(html_doc, "html.parser")
    found = []
    for wrapper in soup.select(".tgme_widget_message_wrap"):
        message = wrapper.select_one(".tgme_widget_message[data-post]")
        if not message:
            continue
        post_id = message.get("data-post", "").split("/")[-1]
        if not post_id.isdigit():
            continue
        text_node = message.select_one(".tgme_widget_message_text")
        if text_node is None:
            text_node = message.select_one(".tgme_widget_message_caption")
        if text_node is None:
            continue
        text = text_node.get_text("\n", strip=True)
        source_url = ""
        for a in text_node.select("a[href]"):
            href = a.get("href", "")
            label = a.get_text(" ", strip=True)
            if ("Источник" in label and href.startswith("http")
                    and "t.me/" not in href):
                source_url = href
                break
        time_node = message.select_one("time[datetime]")
        published = time_node.get("datetime", "") if time_node else ""
        found.append({
            "id": int(post_id),
            "url": f"https://t.me/{CHANNEL}/{post_id}",
            "published": published,
            "text": text[:3500],
            "source_url": source_url,
        })
    return found


def collect_posts(max_pages: int = 30) -> dict:
    all_posts: dict[int, dict] = {}
    next_before = None
    status_notes = []
    for page_num in range(max_pages):
        url = BASE_URL + (f"?before={next_before}" if next_before is not None else "")
        try:
            response = requests.get(
                url, timeout=22,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            status_notes.append(f"page={page_num+1} status={response.status_code} bytes={len(response.content)}")
            response.raise_for_status()
        except requests.RequestException as exc:
            status_notes.append(f"Public Telegram preview unavailable: {type(exc).__name__}")
            break
        discovered = get_posts(response.text)
        if not discovered:
            status_notes.append("Telegram preview has no accessible message captions")
            break
        previous = len(all_posts)
        for post in discovered:
            all_posts[post["id"]] = post
        print(f"Fetched page {page_num+1}: {len(discovered)} posts, total {len(all_posts)}")
        earliest = min(post["id"] for post in discovered)
        if len(all_posts) == previous or earliest == next_before:
            break
        next_before = earliest
        if earliest <= 1:
            break
        time.sleep(0.4)
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "channel": f"@{CHANNEL}",
        "accessible_count": len(all_posts),
        "limitations": status_notes[-4:],
        "posts": sorted(all_posts.values(), key=lambda p: p["id"]),
    }


def run() -> None:
    record = collect_posts()
    RESULT_PATH.parent.mkdir(exist_ok=True)
    RESULT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("PUBLIC CHANNEL AUDIT:", record["accessible_count"], "posts recovered")
    for note in record["limitations"]:
        print("NOTE:", note)
    for post in record["posts"][-12:]:
        lines = post["text"].splitlines()
        print("POST", post["id"], "chars", len(post["text"]),
              "preview", " ".join(lines[:2])[:125])
    if not record["posts"]:
        print("Cannot inspect published message bodies through public preview.")
        # A zero-count record is evidence of a limitation, NOT a success.


if __name__ == "__main__":
    run()
