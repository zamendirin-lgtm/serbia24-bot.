"""Offline dialog learning smoke tests: no paid AI keys and no live chat reads."""
from offline_brain import TRAINING, guess_intent, compose, tokens
from learn_style import empty, learn, preferred_style, sanitize
from chat_replies import classify

def main():
    # Classifier has examples for multiple kinds of youth discussion.
    assert len(TRAINING) >= 6
    assert "дебил" not in tokens("это мнение")
    examples = [
        ("почему эта маска так популярна", "question"),
        ("давай спорить кто победит", "debate"),
        ("ахаха это реально смешно", "joke"),
        ("зацените мой видос", "showcase"),
        ("мне нравится такая эстетика", "opinion"),
        ("всем привет", "greeting"),
        ("это просто имба", "reaction"),
    ]
    for phrase, category in examples:
        intent, confidence = guess_intent(phrase)
        assert intent == category, (phrase, category, intent, confidence)
        assert 0 <= confidence <= 1
        text, explanation = compose(phrase, 745832)
        assert text and len(text) <= 260
        assert explanation["intent"] in TRAINING
    # Popular slang/intent/tone is genuinely learned from safe *synthetic*
    # examples; no usernames, user data or quotes are added to model state.
    style = empty()
    for _ in range(10):
        style = learn("Кринж и имба, но это смешной мем! 😂", style)
    for _ in range(8):
        style = learn("Почему этот костюм такой смешной?", style)
    preference = preferred_style(style)
    assert preference["seen"] == 18, preference
    assert preference["slang"] in ("кринж", "имба")
    assert style["intents"], style
    assert set(style["intents"]).issubset(TRAINING)
    assert "last_message" not in sanitize({**style, "last_message": "private"})
    # These should not train the model or be imitated.
    before = style["seen"]
    style = learn("скинь нюдс", style)
    style = learn("я тебя убью", style)
    style = learn("мне плохо, нужна помощь", style)
    assert style["seen"] == before
    assert classify("ты урод", False) == "harassment"
    # No copying of sender-provided private tokens into the response.
    private = "мой телефон 71234567890 и @private_username"
    result, details = compose(private, 501)
    assert "71234567890" not in result
    assert "@private_username" not in result
    print("LOCAL_OFFLINE_BRAIN_TESTS_OK", len(examples),
          "synthetic examples", sum(map(len, TRAINING.values())),
          "style messages", preference["seen"])

if __name__ == "__main__":
    main()
