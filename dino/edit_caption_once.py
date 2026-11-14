"""One-time edit of the verbose CC BY caption on the previously sent video."""
from bot import CHAT_ID, BOT_TOKEN, load_state, telegram_send
from video_only import minimal_caption

def main():
    if not BOT_TOKEN or CHAT_ID != "-1002244148588":
        raise RuntimeError("Unexpected bot configuration or chat")
    state = load_state()
    if state.get("caption_741497_edited"):
        print("CAPTION_ALREADY_UPDATED")
        return
    hits = state.get("video_search_cache", {}).get("hits", [])
    hit = next((h for h in hits if h.get("id") == "commons-video:5761750"), None)
    if not hit:
        raise RuntimeError("Existing attribution metadata not available")
    text = minimal_caption(hit)
    if not text:
        raise RuntimeError("Cannot silently remove required CC BY credit")
    chat = telegram_send("getChat", data={"chat_id": CHAT_ID})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Not the intended group")
    result = telegram_send("editMessageCaption", data={
        "chat_id": CHAT_ID,
        "message_id": 741497,
        "caption": text,
        "parse_mode": "HTML",
    })
    state["caption_741497_edited"] = True
    from bot import save_state
    save_state(state)
    print("CAPTION_EDITED_OK", result.get("message_id"))

if __name__ == "__main__":
    main()
