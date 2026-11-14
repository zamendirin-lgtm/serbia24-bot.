"""Delete two specific rejected repetitive VS cards from DinoDvij group."""
import bot

IDS = (741507, 741508)

def main():
    if not bot.BOT_TOKEN or bot.CHAT_ID != "-1002244148588":
        raise RuntimeError("Incorrect group or unavailable Telegram token")
    chat = bot.telegram_send("getChat", data={"chat_id":bot.CHAT_ID})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Refusing deletion outside verified supergroup")
    for mid in IDS:
        try:
            bot.telegram_send("deleteMessage", data={"chat_id":bot.CHAT_ID,"message_id":mid})
            print("REJECTED_CARD_REMOVED_OK",mid)
        except RuntimeError as exc:
            print("REJECTED_CARD_DELETE_FAILED",mid,str(exc)[:140])

if __name__ == "__main__":
    main()
