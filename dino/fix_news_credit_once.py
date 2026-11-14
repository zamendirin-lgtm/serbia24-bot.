"""Repair the existing Nov 14 therian news photo attribution without reposting.

Step 1 prepares full CC credit page; workflow commits it before Telegram edit.
Step 2 changes the caption only. The original photo stays untouched.
"""
import sys
import bot
import news_auto as news
from pathlib import Path

CHAT = "-1002244148588"
POST_ID = 741553
PHOTO_ID = "156631916"
STORY_KEY = "tovima-2026-05-21-therians"


def metadata():
    r = bot.HTTP.get(news.COMMONS, params={
        "action": "query", "format": "json", "formatversion": 2,
        "pageids": PHOTO_ID, "prop": "imageinfo",
        "iiprop": "url|extmetadata",
    }, timeout=25)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
    if not isinstance(pages, list) or len(pages) != 1:
        raise RuntimeError("Wikimedia did not return the expected photo page")
    page = pages[0]
    if str(page.get("pageid")) != PHOTO_ID:
        raise RuntimeError("Wrong Wikimedia file")
    info = (page.get("imageinfo") or [{}])[0]
    rights = news.suitable_rights(info.get("extmetadata") or {})
    url = info.get("descriptionurl") or ("https://commons.wikimedia.org/?curid=" + PHOTO_ID)
    if (not rights or not rights.get("credit") or
            "Dyingyote98" not in rights["credit"] or
            "by-sa" not in rights["license"].lower() or
            not news.source_is_valid(url)):
        raise RuntimeError("Photographer/license mismatch. Refuse to edit")
    return rights, url, page.get("title", "")


def context():
    if not bot.BOT_TOKEN or bot.CHAT_ID != CHAT:
        raise RuntimeError("Missing bot token or unexpected Telegram destination")
    state = bot.load_state()
    if STORY_KEY not in state.get("posted_news", []):
        raise RuntimeError("The target article was not published")
    if PHOTO_ID not in state.get("used_news_photos", []):
        raise RuntimeError("Cannot verify the exact published photograph")
    story = next((v for v in news.CURATED if v["key"] == STORY_KEY), None)
    if not story:
        raise RuntimeError("Article not found")
    return story


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("--prepare", "--edit"):
        raise SystemExit("Usage: --prepare or --edit")
    story = context()
    rights, photo_page, name = metadata()
    file = Path(__file__).resolve().parent / "credits" / news.photo_credit_filename(PHOTO_ID)
    expected = news.photo_credit_document(PHOTO_ID, rights, photo_page, name)
    caption = news.format_news_caption(story, rights, photo_page, PHOTO_ID)
    if "Dyingyote98" in caption or "CC BY" in caption or "📷" in caption:
        raise RuntimeError("Visible caption still contains verbose credits")
    if sys.argv[1] == "--prepare":
        news.save_photo_credit(PHOTO_ID, rights, photo_page, name)
        if file.read_text(encoding="utf-8") != expected:
            raise RuntimeError("Saved credits mismatch")
        print("PHOTO_CREDIT_PREPARED_OK", PHOTO_ID)
        return
    if not file.exists() or file.read_text(encoding="utf-8") != expected:
        raise RuntimeError("Full photo attribution page is missing or mismatched")
    chat = bot.telegram_send("getChat", data={"chat_id": CHAT})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Target group not verified")
    try:
        result = bot.telegram_send("editMessageCaption", data={
            "chat_id": CHAT, "message_id": POST_ID,
            "caption": caption, "parse_mode": "HTML",
        })
    except RuntimeError as exc:
        if "message is not modified" in str(exc).lower():
            print("NEWS_CAPTION_ALREADY_MINIMAL", POST_ID)
            return
        raise
    if result.get("message_id") != POST_ID:
        raise RuntimeError("Telegram did not confirm edit")
    print("NEWS_CAPTION_FIXED_OK", POST_ID, "chars", len(caption))


if __name__ == "__main__":
    main()
