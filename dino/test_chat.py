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
    assert c.AUTO_COOLDOWN_SECONDS >= 300
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
    assert c.GROUP_ID == -1002244148588
    print("CHAT_RULES_TESTS_OK",len(expectations))

if __name__ == "__main__":
    main()
