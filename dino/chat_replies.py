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
import learn_style
import offline_brain

STATE_FILE = Path(__file__).resolve().parent / "chat_state.json"
GROUP_ID = -1002244148588
MAX_EVENT_AGE = 12 * 60  # never reply to stale backlog from an interrupted job
MAX_ANSWERS_PER_RUN = 12
MAX_ANSWERS_PER_USER_PER_RUN = 2
DRY_RUN = os.environ.get("DINO_CHAT_DRY_RUN", "false").lower() in ("1", "true", "yes")
BOT_NAME = "@dinodvij_bot"

BANTER = (
    "Ого, заявление. Аргументы в комплекте или это платное DLC? 💀",
    "Ну нифига себе поворот. А пруфы где? 🍿",
    "Понтов на миллион, фактов пока на сдачу 😏",
    "Это звучало громко. Жаль, громкость не заменяет аргументы.",
    "Так, тут начался баттл. Кто принесёт нормальный контраргумент? 🔥",
    "Чат сегодня в режиме «спорим до последнего процента батареи» 💀",
    "Вот это загнул. Интернет сейчас офигеет... или просто пролистает 😂",
    "Не, ну ты выдал. Вторую серию давай, только с сюжетом.",
)

INSULTED_BOT = (
    "Ого, наехали на бота. И это всё? Слабовато, переделывай 💀",
    "Слов много, остроумие где-то застряло на загрузке 😏",
    "Меня послали? Хоть маршрут интересный предложи 😂",
    "А вот это был наезд из архива 2014-го. Есть версия поновее?",
    "Громко. Только меня так легко не заденешь, я из кода 😈",
)

ROAST = (
    "Понтов на миллион, аргументов на сдачу. Красиво живёшь 💀",
    "Ну ты ворвался. А шутка где, брат? Ещё рендерится? 😂",
    "Такой мощный тейк, что даже алгоритмы сказали: «ну нафиг» 😈",
    "Не, это не кринж. Это уже коллекционное издание кринжа 🍿",
    "Если бы уверенность давала просмотры, ты бы уже купил YouTube.",
)

TRENDS = (
    "Терианы VS диносьюты. Не мямлим: кто заберёт этот раунд? 🔥",
    "Маска за три ночи или покупной костюм за ползарплаты? Битва пошла.",
    "Кринж или хайп: динозавр в супермаркете? Только не юлите 🦖",
    "Идеальный монтаж или эпичный фейл — что реально залетит? 🍿",
)

NORMAL = (
    "Ну всё, приехали. И как ты это докажешь? 💀",
    "Смелое мнение. Комменты уже достают попкорн 🍿",
    "Да ну нафиг. Кто-нибудь объяснит, почему это работает? 😏",
)

HARASSMENT_REPLY = (
    "Эй, хорош цепляться к человеку. Наезжай на идею, не на участника.",
    "Это уже не баттл, а дешёвый наезд. Верни нормальные аргументы.",
    "Стоп, персональные оскорбления — фиговый контент. По теме давай.",
)

THREAT_REPLY = "Угрозы — не дерзость, а дичь. Заканчивай и не трогай участников."
SEXUAL_REPLY = "Стоп. Здесь есть подростки, такой контент сюда не тащи."
HELP_REPLY = "Я сам врываюсь в обсуждения. Хочешь баттл — /battle, хочешь прожарку — /roast. 😈"

TOPIC_REPLIES = {
    "therian": (
        "Терианские маски снова взорвали комменты. И кто тут решит, что реально стиль? 🐾",
        "Ага, очередной спор про териан. Не нойте, лучше покажите мощный образ 😈",
    ),
    "dino": (
        "Диносьют выглядит грозно, пока не встретил дверной проём 💀",
        "Динозавр в костюме — легенда. Только не застрянь в дверях, герой 🦖",
    ),
    "quad": (
        "Квадробика на видео — имба. В жизни физика говорит: «держи меня семеро» 😂",
        "Ну что, прыжок эпичный или монтаж спас ситуацию? 🍿",
    ),
    "meme": (
        "Такой кринж, что он уже почти стал искусством. Почти 💀",
        "Интернет опять превратил полную хрень в тренд. А вы ведётесь? 😈",
    ),
    "costume": (
        "Костюм на ползарплаты, просмотров на пачку сухариков. Знакомо? 💀",
        "Образ реально мощный или всё держится на хорошем свете? Не стесняйтесь 😏",
    ),
    "debate": (
        "Ну понеслась. У кого пруфы, а у кого просто громкий голос? 🍿",
        "С такими тейками спор до утра обеспечен. Давайте без дешёвых наездов.",
    ),
    "chat": (
        "Вы тут что, новый сезон драмы снимаете без меня? 🍿",
        "Чат опять в огне. Кто-нибудь вообще помнит, с чего началось? 💀",
    ),
}

TOPIC_PATTERNS = (
    ("therian", re.compile(r"териан|терриан|therian", re.I)),
    ("dino", re.compile(r"диносьют|диносют|dinosuit|динозавр|dinosaur", re.I)),
    ("quad", re.compile(r"квадроб|quadrob", re.I)),
    ("costume", re.compile(r"маск[аиуе]|костюм|fursuit|cosplay|образ", re.I)),
    ("meme", re.compile(r"мем|кринж|cringe|лол|имба|жиза|рилс|shorts|тикток|видос", re.I)),
    ("debate", re.compile(r"спор|против|кто круче|лучше|почему|не соглас|топ|отстой|нормально|хайп", re.I)),
)
CHAT_HOOK = re.compile(
    r"\b(?:серьёзно|реально|вообще|блин|ахах|хаха|прикол|ржака|"
    r"почему|кто|как|чего|может|у меня|я думаю|мне кажется|"
    r"ладно|жесть|капец|смотрите)\b", re.I
)
AUTO_COOLDOWN_SECONDS = 8 * 60
AUTO_REPLIES_PER_RUN = 2

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
    r"слей(?:те)?\s+(?:адрес|номер)|найду\s+тебя\s+и\s+|"
    r"(?:я\s+)?тебя\s+(?:убью|зарежу|побью))\b",
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
                    "total_replies": int(state.get("total_replies", 0)),
                    "last_spontaneous_at": int(state.get("last_spontaneous_at", 0)),
                    "announcement_message_id": int(state.get("announcement_message_id", 0)),
                    "style": learn_style.sanitize(state.get("style"))}
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


def spontaneous_category(text, message_id):
    """Choose an occasional unsolicited remark only for active, light discussion."""
    cleaned = text.strip()
    if len(cleaned) < 12 or len(cleaned) > 500:
        return None
    low = cleaned.lower()
    # Never crack jokes over somebody's distress or private problems.
    if any(word in low for word in (
        "помогите", "мне плохо", "депресс", "умер", "похорон",
        "болит", "больниц", "суицид", "самоуб", "избил",
        "травят", "травля", "страшно", "страда",
    )):
        return None
    # Always eligible to be considered when the chat is about its interests.
    for category, pattern in TOPIC_PATTERNS:
        if pattern.search(cleaned):
            return category
    # In general chat, join only occasional open opinions/questions.
    if not ("?" in cleaned or "!" in cleaned or CHAT_HOOK.search(cleaned)):
        return None
    if (message_id * 37 + 17) % 7 < 2:
        return "chat"
    return None


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
    if category in TOPIC_REPLIES:
        return rng.choice(TOPIC_REPLIES[category])
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
    state["style"] = learn_style.sanitize(state.get("style"))
    old_offset = int(state.get("offset") or 0)
    offset = old_offset
    now = time.time()
    replied = 0
    spontaneous = 0
    last_auto_at = int(state.get("last_spontaneous_at", 0))
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
                # First live poll establishes a cursor; never reply to past chat history.
                if old_offset == 0 and not DRY_RUN:
                    continue
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
                # Anonymous aggregate vocabulary/format training. No text or
                # user ID is persisted; serious distress is ignored.
                state["style"] = learn_style.learn(body, state["style"])
                replied_to = msg.get("reply_to_message", {}).get("from", {})
                direct = bool(
                    MENTION.search(body) or BOT_COMMAND.search(body) or
                    replied_to.get("id") == bot_user_id
                )
                category = classify(body, direct)
                is_spontaneous = False
                # Join discussions on its own, without needing @mention.
                if category is None:
                    if spontaneous >= AUTO_REPLIES_PER_RUN:
                        continue
                    msg_time = int(msg.get("date") or 0)
                    if msg_time < last_auto_at + AUTO_COOLDOWN_SECONDS:
                        continue
                    category = spontaneous_category(body, original_msg_id)
                    is_spontaneous = bool(category)
                if not category:
                    continue
                uid = user.get("id", 0)
                if per_user.get(uid, 0) >= (1 if is_spontaneous else MAX_ANSWERS_PER_USER_PER_RUN):
                    continue
                if replied >= MAX_ANSWERS_PER_RUN:
                    continue
                style = learn_style.preferred_style(state["style"])
                # First enforce moderation. Only ordinary conversation gets
                # local classifier-composed replies, never unsafe raw copying.
                response = choose_reply(category, original_msg_id)
                if category not in ("threat", "sexual", "harassment",
                                    "bot_insult", "help") and original_msg_id % 4:
                    generated, interpretation = offline_brain.compose(
                        body, original_msg_id, {**style, "intents": state["style"].get("intents", {})},
                        tone=category
                    )
                    if generated:
                        response = generated
                    print("LOCAL_INTENT", interpretation["intent"],
                          "topic", interpretation["topic"])
                response = learn_style.adapt_reply(
                    response, style, original_msg_id, category
                )
                sent = False
                if DRY_RUN:
                    print("CHAT_DRY_RUN_ANSWER", category, "spontaneous", is_spontaneous)
                    replied += 1
                    sent = True
                else:
                    try:
                        if send_reply(response, original_msg_id):
                            replied += 1
                            sent = True
                    except (RuntimeError, requests.RequestException):
                        print("CHAT_REPLY_FAILED")
                if sent:
                    per_user[uid] = per_user.get(uid, 0) + 1
                    if is_spontaneous:
                        spontaneous += 1
                        last_auto_at = int(msg.get("date", now))
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
        state["last_spontaneous_at"] = last_auto_at
        save_state(state)
    style_summary = learn_style.preferred_style(state["style"])
    print("CHAT_POLL_OK", "processed", processed,
          "replied", replied, "spontaneous", spontaneous,
          "learned_message_count", style_summary["seen"],
          "learned_style", style_summary["length"],
          "offset_changed", offset != old_offset)


if __name__ == "__main__":
    main()
