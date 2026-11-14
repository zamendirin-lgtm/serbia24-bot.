"""Shorten the published Pyrkon video credit to a single linked info icon."""
import bot
from pathlib import Path
from video_only import minimal_caption, credit_document, credit_filename

CHAT = "-1002244148588"
MESSAGE_ID = 741512
MEDIA_ID = "commons-video:195011858"

def main():
    if not bot.BOT_TOKEN or bot.CHAT_ID != CHAT:
        raise RuntimeError("Unexpected bot chat or missing token")
    state = bot.load_state()
    if MEDIA_ID not in state.get("used_media", []):
        raise RuntimeError("Cannot confirm this video was published")
    if state.get("video_info_caption_741512"):
        print("VIDEO_INFO_CAPTION_ALREADY_EDITED")
        return
    hits = state.get("video_search_cache", {}).get("hits", [])
    hit = next((x for x in hits if x.get("id") == MEDIA_ID), None)
    if hit is None:
        raise RuntimeError("Cannot verify video source and license")
    credit_file = Path(__file__).resolve().parent / "credits" / credit_filename(hit)
    if not credit_file.exists():
        raise RuntimeError("Attribution page must be published before caption edit")
    if credit_file.read_text(encoding="utf-8") != credit_document(hit):
        raise RuntimeError("Attribution page does not match original license")
    chat = bot.telegram_send("getChat", data={"chat_id": CHAT})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Refusing to edit outside the group")
    caption = minimal_caption(hit)
    result = bot.telegram_send("editMessageCaption", data={
        "chat_id": CHAT, "message_id": MESSAGE_ID,
        "caption": caption, "parse_mode": "HTML",
    })
    if result.get("message_id") != MESSAGE_ID:
        raise RuntimeError("Telegram did not confirm caption edit")
    state["video_info_caption_741512"] = True
    bot.save_state(state)
    print("VIDEO_INFO_CAPTION_UPDATED_OK", MESSAGE_ID)

if __name__ == "__main__":
    main()
