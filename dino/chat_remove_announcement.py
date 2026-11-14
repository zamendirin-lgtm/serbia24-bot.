"""Remove only the unwanted DinoDvij command announcement from the group."""
from bot import BOT_TOKEN, CHAT_ID, telegram_send
from chat_replies import read_state, save_state

def main():
    if not BOT_TOKEN or str(CHAT_ID) != "-1002244148588":
        raise RuntimeError("Incorrect bot destination")
    state = read_state()
    msg = int(state.get("announcement_message_id", 0))
    if msg != 741503:
        print("NO_ANNOUNCEMENT_TO_DELETE")
        return
    chat = telegram_send("getChat", data={"chat_id": CHAT_ID})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Refusing to delete message outside intended group")
    telegram_send("deleteMessage", data={"chat_id": CHAT_ID, "message_id": msg})
    state["announcement_message_id"] = 0
    save_state(state)
    print("ANNOUNCEMENT_DELETED_OK", msg)

if __name__ == "__main__":
    main()
