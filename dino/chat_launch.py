"""Announce the new DinoDvij bot chat commands once in the verified group."""
import bot
from chat_replies import read_state, save_state

def main():
    if not bot.BOT_TOKEN or bot.CHAT_ID != "-1002244148588":
        raise RuntimeError("Unexpected destination or missing bot token")
    state = read_state()
    if state.get("announcement_message_id"):
        print("CHAT_LAUNCH_ALREADY_ANNOUNCED")
        return
    chat = bot.telegram_send("getChat", data={"chat_id":bot.CHAT_ID})
    if chat.get("type") != "supergroup":
        raise RuntimeError("Not the verified Telegram group")
    message = (
        "🦖 ЭЙ, ЧАТ!\n\n"
        "Я теперь могу отвечать, подколоть и устроить спор. "
        "Напиши @DinoDvij_bot или /roast — посмотрим, насколько у тебя крепкий юмор 😈\n\n"
        "Для баттла попробуй /battle. "
        "Подколы и мемы — да. Травля других участников — нет. 🍿"
    )
    result = bot.telegram_send("sendMessage", data={
        "chat_id":bot.CHAT_ID, "text":message, "disable_notification":"true"
    })
    mid = result.get("message_id")
    if not mid:
        raise RuntimeError("Telegram did not acknowledge the announcement")
    state["announcement_message_id"] = mid
    save_state(state)
    print("CHAT_LAUNCH_POSTED_OK",mid)

if __name__ == "__main__":
    main()
