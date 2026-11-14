"""Edit one published news caption, leaving its excellent photo untouched."""
from __future__ import annotations

import bot
import news_auto as news

CHAT_ID = "-1002244148588"
MESSAGE_ID = 741511
PHOTO_PAGE_ID = 3862418
STORY_KEY = "canal10-2026-10-16-quadrobics"

def original_image_rights():
    response = bot.HTTP.get(news.COMMONS, params={
        "action": "query", "format": "json", "formatversion": 2,
        "pageids": PHOTO_PAGE_ID, "prop": "imageinfo",
        "iiprop": "url|extmetadata",
    }, timeout=20)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", [])
    if len(pages) != 1 or int(pages[0].get("pageid", 0)) != PHOTO_PAGE_ID:
        raise RuntimeError("Cannot verify credited photo metadata")
    info = (pages[0].get("imageinfo") or [{}])[0]
    rights = news.suitable_rights(info.get("extmetadata", {}))
    url = info.get("descriptionurl", "")
    if not rights or not rights.get("credit") or not news.source_is_valid(url):
        raise RuntimeError("Unable to verify complete CC BY-SA photo attribution")
    if "cc by-sa" not in rights["license"].lower():
        raise RuntimeError("Photo license unexpectedly changed")
    return rights, url

def main():
    if not bot.BOT_TOKEN or bot.CHAT_ID != CHAT_ID:
        raise RuntimeError("Unexpected bot group or missing token")
    chat = bot.telegram_send("getChat", data={"chat_id": CHAT_ID})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Refusing to edit a post outside the group")
    state = bot.load_state()
    if STORY_KEY not in state.get("posted_news", []):
        raise RuntimeError("The verified article was not published")
    if str(PHOTO_PAGE_ID) not in state.get("used_news_photos", []):
        raise RuntimeError("Photo used on the published post does not match")
    story = next((x for x in news.CURATED if x["key"] == STORY_KEY), None)
    if not story:
        raise RuntimeError("Article no longer exists")
    rights, page = original_image_rights()
    caption = news.format_news_caption(story, rights, page)
    result = bot.telegram_send("editMessageCaption", data={
        "chat_id": CHAT_ID, "message_id": MESSAGE_ID,
        "caption": caption, "parse_mode": "HTML"
    })
    print("NEWS_CAPTION_UPDATED_OK", result.get("message_id"),
          "characters", len(caption))

if __name__ == "__main__":
    main()
