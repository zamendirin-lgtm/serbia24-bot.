"""One-time welcome post, sent directly into the verified Telegram group."""
from pathlib import Path

from bot import CHAT_ID, BOT_TOKEN, ROOT, load_state, save_state, poster, telegram_send


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Missing Telegram configuration")
    state = load_state()
    if state.get("welcome_posted"):
        print("Welcome already posted; skipping")
        return
    target = telegram_send("getChat", data={"chat_id": CHAT_ID})
    if target.get("type") not in ("group", "supergroup"):
        raise RuntimeError("Expected Telegram group; refusing to post")
    me = telegram_send("getMe")
    member = telegram_send("getChatMember", data={
        "chat_id": CHAT_ID, "user_id": me["id"]
    })
    if member.get("status") not in ("administrator", "creator"):
        raise RuntimeError("Bot does not have administrator permissions")
    photo = poster("Добро пожаловать в ДИНОДВИЖ!")
    caption = (
        "🐾 ТЕРРИАНЫ & ДИНОСЬЮТЫ 🦖\n\n"
        "Привет, сообщество! Мы запускаем подборку интересных новостей, "
        "необычных костюмов, смешных видео, мемов и историй про наши увлечения. 🐉\n\n"
        "Здесь можно общаться, обсуждать и делиться своими находками. "
        "Без оскорблений и травли — пусть будет интересно всем! 🔥\n\n"
        "Кто из вас за терриан, кто за диносьютов, а кто просто любит мемы? 👀"
    )
    try:
        with open(photo, "rb") as handle:
            result = telegram_send(
                "sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"photo": ("welcome.jpg", handle, "image/jpeg")}
            )
    finally:
        Path(photo).unlink(missing_ok=True)
    state["welcome_posted"] = True
    state["welcome_message_id"] = result.get("message_id")
    save_state(state)
    print("WELCOME_POSTED_OK, message_id:", result.get("message_id"))


if __name__ == "__main__":
    main()
