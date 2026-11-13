"""One-time edit of the existing Mars Telegram photo caption, without reposting."""
import re
import sys

import requests
from bs4 import BeautifulSoup

import bot
from publish_now import KEY, content


def find_post_id():
    # Telegram has no getMessage endpoint; use the channel's public preview to
    # locate precisely the one photo post by its unique text, not by guessing IDs.
    urls = ("https://t.me/s/priroda_realnosti", "https://t.me/priroda_realnosti")
    for url in urls:
        try:
            response = requests.get(url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RealityEditorial/1.0)"},
                timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for div in soup.select(".tgme_widget_message[data-post]"):
                body = div.get_text(" ", strip=True)
                if ("На Марсе нашли органические соединения" in body and
                    "Perseverance" in body and
                    ("ScienceDaily" in body or "органическ" in body)):
                    post = div.get("data-post", "")
                    match = re.fullmatch(r"priroda_realnosti/(\d+)", post, re.I)
                    if match:
                        return int(match.group(1))
        except requests.RequestException as exc:
            print("PREVIEW_UNAVAILABLE", type(exc).__name__)
    return None


def main():
    state = bot.read_state()
    entry = state.get("posted", {}).get(KEY, {})
    if entry.get("image_id") != "commons:104897482":
        print("EDIT_SKIPPED: expected photo publication was not found in state")
        sys.exit(1)
    message_id = find_post_id()
    if message_id is None:
        print("EDIT_NOT_PERFORMED: existing post ID could not be retrieved safely from public channel")
        sys.exit(1)
    media = {"page": "https://commons.wikimedia.org/?curid=104897482",
             "license": {"name": "Public domain", "credit": "", "lic_url": ""}}
    updated = content(media)
    if len(updated) > 1024:
        print("EDIT_SKIPPED: new caption too long")
        sys.exit(1)
    bot.telegram("editMessageCaption", {
        "chat_id": bot.CHAT,
        "message_id": str(message_id),
        "caption": updated,
        "parse_mode": "HTML"
    })
    print("EXISTING_MARS_CAPTION_EDITED", message_id, "in place; no duplicate post")


if __name__ == "__main__":
    main()
