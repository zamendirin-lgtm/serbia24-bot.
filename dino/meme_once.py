"""Publish one original meme as a Telegram photo in the existing group."""
from datetime import datetime
from bot import BOT_TOKEN, CHAT_ID, TZ, load_state, save_state, telegram_send
from memes import post_meme

def main():
    if not BOT_TOKEN or CHAT_ID != "-1002244148588":
        raise RuntimeError("Missing token or incorrect destination")
    chat = telegram_send("getChat", data={"chat_id":CHAT_ID})
    if chat.get("type") not in ("group", "supergroup"):
        raise RuntimeError("Target is not the intended group")
    state = load_state()
    day = datetime.now(TZ).date().isoformat()
    if state.get("date") != day:
        state["date"] = day
        state["daily_count"] = 0
    if post_meme(state, force=True):
        state["daily_count"] = state.get("daily_count", 0) + 1
        save_state(state)

if __name__ == "__main__":
    main()
