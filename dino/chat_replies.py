"""DinoDvij group banter and anti-harassment replies.

Reads only fresh messages from the configured Telegram group, replies to direct
mentions/commands or obvious personal harassment, and does not retain personal
text/user IDs in the public GitHub repository. This is template-based, not an
LLM: no third-party chat model and no hidden bot API costs.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

import bot

STATE_FILE = Path(__file__).resolve().parent / "chat_state.json"
GROUP_ID = -1002244148588
MAX_EVENT_AGE = 12 * 60  # never reply to stale backlog from an interrupted job
MAX_ANSWERS_PER_RUN = 12
MAX_ANSWERS_PER_USER_PER_RUN = 2
DRY_RUN = os.environ.get("DINO_CHAT_DRY_RUN", "false").lower() in ("1", "true", "yes")
BOT_NAME = "@dinodvij_bot"

BANTER = (
    "Ну, такое заявление на миллион просмотров. А доказательства где? 🍿",
    "Громко сказано. Теперь ждём сюжетный поворот 😏",
    "Вот это уверенность! Осталось интернет убедить 😂",
    "Мне нравится масштаб драмы. Продолжай, но без переходов на личности.",
    "Спор принят. У кого аргументы смешнее — тот и выиграл 🦖",
    "Похоже, комментарии сегодня решили устроить финал сезона 🍿",
    "Согласен только с тем, что скучно у нас точно не будет 💀",
    "Ладно, это было дерзко. А теперь вариант без капслока? 😂",
)
INSULTED_BOT = (
    "Эффектно зашёл. А шутку получше завезут или это финальная версия? 😏",
    "Так, чат, записываем: главный аргумент дня — капслок и эмоции. 🍿",
    "Провокацию вижу. А остроумие пока не загрузилось 💀",
    "Ты меня пытался задеть? Я же бот. Давай что-нибудь поинтереснее 😈",
    "На слабый наезд отвечаю слабым аплодисментом. 👏",
)
ROAST = (
    "Твой комментарий так уверенно звучит, будто за ним хотя бы три аргумента. А где они? 💀",
    "С такой драмой тебе не в чат, а в трейлер нового сезона 😂",
    "Принял вызов. Пока баттл выигрывает автозамена, а не ты 😏",
    "Это был заявленный огонь, а вышло предупреждение о низком заряде 🔋",
    "Твой план звучит эпично. Реализация пока в режиме «загрузка...» 🌀",
)
TRENDS = (
    "Терианы или диносьюты — кто делает более смешные ролики? Только аргументы, а не наезды 🔥",
    "Честный баттл: маска своими руками или готовый образ? 🐾",
    "Кринж или хайп: костюм динозавра в супермаркете? Обсуждаем 🦖",
    "Что больше залетает: идеальный монтаж или случайный фейл? 🍿",
)
NORMAL = (
    "О, меня позвали. Здесь у нас спорят с аргументами и мемами, не с людьми 😈",
    "Я тут. Хочешь баттл, мем или язвительный ответ? 🦖",
    "Окей, я на связи. Напиши /roast, если хочешь лёгкий подкол 😏",
)
HARASSMENT_REPLY = (
    "Стендап из оскорблений? Не зашло. Спорьте по теме, без травли людей.",
    "Эй, без наездов на участников. Можешь спорить жёстко, но не унижать людей.",
    "Убери персональные оскорбления. С аргументами этот баттл будет интереснее.",
)
THREAT_REPLY = "Угрозы и призывы к насилию здесь не игра. Остановись и не направляй их на участников."
SEXUAL_REPLY = "В этом чате есть несовершеннолетние. Такие предложения здесь неуместны."
HELP_REPLY = "Я отвечаю на @DinoDvij_bot, /roast и /battle. Подколы — да, травля — нет. Видео и мемы публикуются отдельно."

# Match direct insults / harassment, not every slang word in casual chat.
PERSONAL_ABUSE = re.compile(
    r"\b(?:сдохни|убейся|иди\s+нах(?:уй)?|пош[её]л\s+нах(?:уй)?|"
    r"ты\s+(?:туп(?:ой|ая)|урод|дебил|дау[нм]|чмо|лох)|"
    r"заткнись|ничтожество|тварь|"
    r"пошла\s+нах(?:уй)?|шлюха|соси\s+\S+)\b",
    re.I,
)
THREATS = re.compile(
    r"\b(?:убью\s+(?:тебя|вас)|побью\s+(?:тебя|вас)|зарежу|"
    r"слей(?:те)?\s+(?:адрес|номер)|найду\s+тебя\s+и\s+)\b",
    re.I,
)
SEXUAL = re.compile(r"\b(?:скинь\s+нюдс|скинь\s+интим|пришли\s+гол(?:ые|ую))\b", re.I)
MENTION = re.compile(r"(?<!\w)@dinodvij_bot\b", re.I)
BOT_COMMAND = re.compile(r"^/(?:roast|battle|start|help|dino|бот)(?:@dinodvij_bot)?(?:\s|$)", re.I)
PRONOUN = re.compile(r"\b(?:ты|тебя|тебе|вам|вы|твой|твоя|ваш|твои)\b", re.I)


def read_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {"offset": 0}
    except (OSError, ValueError):
        return {"offset": 0}


def save_state(state):
    # Never store group message text, usernames, IDs, profiles or handles here.
    public_state = {"offset": int(state.get("offset", 0)),
                    "last_check_utc": datetime.now(timezone.utc).isoformat(),
                    "total_replies": int(state.get("total_replies", 0))}
    STATE_FILE.write_text(
        json.dumps(public_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def classify(text, to_bot):
    cleaned = text.strip()
    low = cleaned.lower()
    if THREATS.search(cleaned):
        return "threat"
    if SEXUAL.search(cleaned):
        return "sexual"
    # If a user swears at the bot itself, joke about the wording rather than
    # humiliating the person. If somebody attacks a participant, intervene.
    if PERSONAL_ABUSE.search(cleaned):
        without_bot_mention = MENTION.sub("", cleaned)
        if to_bot and not re.search(r"@\w+", without_bot_mention, re.I):
            return "bot_insult"
        if PRONOUN.search(cleaned) or re.search(r"@\w+", cleaned):
            return "harassment"
    if not to_bot:
        return None
    if low.startswith(("/help", "/start")):
        return "help"
    if low.startswith(("/roast", "/dino")) or "подколи" in low or "прожарь" in low:
        return "roast"
    if low.startswith("/battle") or "баттл" in low or "кто круче" in low:
        return "battle"
    if re.search(r"\b(?:тупой|дурной|лох|иди нах|отстой|кринжовый)\b", low):
        return "bot_insult"
    return "banter"


def choose_reply(category, msg_id):
    rng = random.Random(msg_id * 7919)
    if category == "threat":
        return THREAT_REPLY
    if category == "sexual":
        return SEXUAL_REPLY
    if category == "harassment":
        return rng.choice(HARASSMENT_REPLY)
    if category == "bot_insult":
        return rng.choice(INSULTED_BOT)
    if category == "help":
        return HELP_REPLY
    if category == "roast":
        return rng.choice(ROAST)
    if category == "battle":
        return rng.choice(TRENDS)
    return rng.choice(BANTER if msg_id % 3 else NORMAL)


def send_reply(text, original_msg_id):
    result = bot.telegram_send(
        "sendMessage",
        data={
            "chat_id": bot.CHAT_ID,
            "text": text,
            "reply_parameters": json.dumps(
                {"message_id": original_msg_id, "allow_sending_without_reply": False}
            ),
            "disable_notification": "true",
            "link_preview_options": json.dumps({"is_disabled": True}),
        },
    )
    return bool(result.get("message_id"))


def main():
    if not bot.BOT_TOKEN or str(bot.CHAT_ID) != str(GROUP_ID):
        print("CHAT_NOT_CONFIGURED")
        return
    # This prevents private messages from being sent to the public group
    # and keeps live chat scoped strictly to the requested community.
    target = bot.telegram_send("getChat", data={"chat_id": bot.CHAT_ID})
    if target.get("type") not in ("supergroup", "group"):
        print("CHAT_WRONG_GROUP_TYPE")
        return
    me = bot.telegram_send("getMe")
    bot_user_id = me.get("id")
    state = read_state()
    old_offset = int(state.get("offset") or 0)
    offset = old_offset
    now = time.time()
    replied = 0
    per_user = {}
    processed = 0
    try:
        for _ in range(3):
            updates = bot.telegram_send(
                "getUpdates",
                data={
                    "offset": offset,
                    "timeout": 0,
                    "limit": 100,
                    "allowed_updates": json.dumps(["message"]),
                },
            )
            if not updates:
                break
            for update in updates:
                update_id = int(update.get("update_id", -1))
                if update_id < offset:
                    continue
                offset = update_id + 1
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                if chat.get("id") != GROUP_ID:
                    continue
                user = msg.get("from", {})
                if not user or user.get("is_bot") or msg.get("sender_chat"):
                    continue
                original_msg_id = msg.get("message_id")
                if not original_msg_id or now - int(msg.get("date", 0)) > MAX_EVENT_AGE:
                    continue
                body = str(msg.get("text") or msg.get("caption") or "")[:1500]
                if not body:
                    continue
                replied_to = msg.get("reply_to_message", {}).get("from", {})
                direct = bool(
                    MENTION.search(body) or BOT_COMMAND.search(body) or
                    replied_to.get("id") == bot_user_id
                )
                category = classify(body, direct)
                if not category:
                    continue
                uid = user.get("id", 0)
                if per_user.get(uid, 0) >= MAX_ANSWERS_PER_USER_PER_RUN:
                    continue
                if replied >= MAX_ANSWERS_PER_RUN:
                    continue
                response = choose_reply(category, original_msg_id)
                if DRY_RUN:
                    print("CHAT_DRY_RUN_ANSWER", category)
                    replied += 1
                else:
                    try:
                        if send_reply(response, original_msg_id):
                            replied += 1
                    except (RuntimeError, requests.RequestException) as exc:
                        print("CHAT_REPLY_FAILED", type(exc).__name__)
                        # Do not retry individual messages or log their content.
                per_user[uid] = per_user.get(uid, 0) + 1
            processed += len(updates)
            if len(updates) < 100:
                break
    except (RuntimeError, requests.RequestException) as exc:
        print("CHAT_POLL_FAILED", type(exc).__name__,
              "Another webhook/poller may own getUpdates")
        return

    if not DRY_RUN:
        state["offset"] = offset
        state["total_replies"] = int(state.get("total_replies", 0)) + replied
        save_state(state)
    print("CHAT_POLL_OK", "processed", processed,
          "replied", replied, "offset_changed", offset != old_offset)


if __name__ == "__main__":
    main()
