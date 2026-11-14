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
    assert c.GROUP_ID == -1002244148588
    print("CHAT_RULES_TESTS_OK",len(expectations))

if __name__ == "__main__":
    main()
