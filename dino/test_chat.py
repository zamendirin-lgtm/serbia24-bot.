"""Fast offline tests for group reply safety and tone."""
import chat_replies as c

def main():
    expectations = [
        (("@DinoDvij_bot привет", True), "banter"),
        (("@dinodvij_bot ты тупой", True), "bot_insult"),
        (("ты урод", False), "harassment"),
        (("давай я тебя убью", False), "threat"),
        (("скинь нюдс", False), "sexual"),
        (("/roast", True), "roast"),
        (("/battle", True), "battle"),
        (("/help", True), "help"),
        (("Сегодня я тестирую маску", False), None),
        (("новые видосы мне нравятся", False), None),
        (("@DinoDvij_bot кринжовый", True), "bot_insult"),
    ]
    for args, expected in expectations:
        actual = c.classify(*args)
        assert actual == expected, (args, expected, actual)
        if actual:
            reply = c.choose_reply(actual, 54)
            assert reply and len(reply) <= 300
    # Spontaneous response to ordinary themed chat, even without a mention.
    assert c.classify("Мне нравится эта маска терриана", False) is None
    assert c.spontaneous_category("Мне нравится эта маска терриана", 12345) == "therian"
    assert c.spontaneous_category("Диносьюты реально смешнее всех", 12346) == "dino"
    assert c.spontaneous_category("Сегодня мне плохо, нужна помощь", 12347) is None
    assert c.spontaneous_category("Привет", 12348) is None
    assert c.classify("ты урод", False) == "harassment"
    assert c.AUTO_COOLDOWN_SECONDS >= 180
    assert c.AUTO_REPLIES_PER_RUN <= 3
    # The offline learner adapts from aggregate counts, never raw messages
    # or personal identifiers, and avoids learning from distress.
    import json
    import tempfile
    from pathlib import Path
    import learn_style as learner
    style = learner.empty()
    for _ in range(14):
        style = learner.learn("Кринж, но это имба! 😂", style)
    style = learner.learn("мне плохо, нужна помощь", style)
    preferred = learner.preferred_style(style)
    assert preferred["seen"] == 14
    assert preferred["slang"] in ("кринж", "имба")
    assert preferred["emoji"]
    assert learner.preferred_style(learner.empty())["slang"] is None
    assert learner.adapt_reply("Дерзкая реплика!", preferred, 15, "harassment") == "Дерзкая реплика!"
    with tempfile.TemporaryDirectory() as td:
        old_file = c.STATE_FILE
        c.STATE_FILE = Path(td) / "state.json"
        try:
            c.save_state({"offset": 8, "style": style,
                          "message_text": "Мой адрес 12345678",
                          "username": "@secret_user",
                          "user_id": 7654321})
            encoded = c.STATE_FILE.read_text(encoding="utf-8")
            assert "12345678" not in encoded
            assert "@secret_user" not in encoded
            assert "7654321" not in encoded
            assert c.read_state()["style"]["seen"] == 14
        finally:
            c.STATE_FILE = old_file
    # Regression from a real chat: a neutral question about the group's
    # creator is not a fight, and the bot must not invent one.
    for message in (
        "То есть злой админ это не создатель?",
        "А кто тогда создатель?",
        "Конечно нет, но один из самых старых админов в чате.",
        "Какой спор?",
        "Кто владелец чата?",
        "Я думаю у нас вообще ничего не произошло",
        "Скажите, а кто сегодня будет в чате?",
    ):
        assert c.spontaneous_category(message, 746200) is None, message
    assert c.classify("@DinoDvij_bot кто создатель чата?", True) == "group_roles"
    answer = c.choose_reply("group_roles", 746201)
    assert "не знаю" in answer and "спор" not in answer
    assert c.spontaneous_category("Смотри мою маску терриана — как тебе?", 746201) == "therian"
    assert c.spontaneous_category("В костюме динозавра я еле прошёл в дверь 😂", 746202) == "dino"
    # Screenshot regression: a threat to a dog is not a harmless meme.
    assert c.classify("на питбайке задавлю собаку", False) == "animal_threat"
    assert "не рофл" in c.choose_reply("animal_threat", 778811)
    assert c.spontaneous_category("Сейчас в тренде газява", 778812) == "new_trend"
    assert c.spontaneous_category("Переименуйте чат в чат питбайкеров", 778813) == "chat_rename"
    assert c.spontaneous_category("Сняли угарный ролик на питбайке", 778814) == "pitbike"
    assert c.is_safe_topic_reply({"text": "Сейчас в тренде газява"})
    assert not c.is_safe_topic_reply({"text": "Кто создал этот чат?"})
    assert c.MAX_LEARNING_AGE > c.MAX_REPLY_AGE
    # Relevant context is counted even if automatic answer is skipped.
    before = learner.empty()
    after = learner.learn("это реально смешной мем", before)
    assert after["seen"] == 1 and after["topics"]["meme"] == 1
    assert learner.learn("на питбайке задавлю собаку", after)["seen"] == 1
    assert c.classify("А если я казах, то лошадь можно переехать?", False) == "horse_safety"
    assert c.classify("А собаку можно задавить?", False) == "animal_threat"
    assert c.choose_reply("horse_safety", 800) in c.HORSE_TROLL_REPLIES
    assert c.choose_reply("horse_safety", 800) == c.choose_reply("horse_safety", 800)
    # Dark humor targets an absurd idea, never ethnicity or actual violence.
    for reply in c.HORSE_TROLL_REPLIES:
        assert "казах" not in reply.lower()
        assert not any(x in reply.lower() for x in ("задавлю", "сбей", "перееду", "убей"))
        assert len(reply) <= 170
    assert c.classify("бот молчишь, ответь хоть раз", False) == "bot_insult"
    assert c.classify("бот не отвечает, он тупой", False) == "bot_insult"
    assert c.classify("Сегодня бот загрузил новости", False) is None
    assert c.classify("на питбайке задавлю собаку", False) == "animal_threat"
    assert c.classify("@DinoDvij_bot ты бот?", True) == "rooster"
    assert c.classify("ты бот?", False) == "rooster"
    assert c.classify("ты человек?", True) == "rooster"
    assert c.classify("@DinoDvij_bot кто ты?", True) == "rooster"
    assert c.classify("@dinodvij_bot ты тупой", True) == "bot_insult"
    for category in ("rooster", "bot_insult"):
        for msg_id in range(33, 44):
            reply = c.choose_reply(category, msg_id)
            assert "Я петух" in reply, reply
            assert "я бот" not in reply.lower()
    assert c.GROUP_ID == -1002244148588
    print("CHAT_RULES_TESTS_OK",len(expectations))

if __name__ == "__main__":
    main()
