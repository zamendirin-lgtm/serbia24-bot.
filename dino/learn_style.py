"""Tiny local online-style learner for a public Telegram group.

This is not a trained LLM. It learns safe aggregate vocabulary/format preferences
from chat activity and adjusts the bot's scripted voice with no paid AI API.
It NEVER persists raw message bodies, names, handles, per-person profiles,
quoted phrases or full token sequences.
"""
from __future__ import annotations

import re
from collections import Counter

# Explicitly reviewed slang only. Unknown or personally identifying words
# will never be learned or repeated automatically.
SAFE_SLANG = {
    "кринж": (r"\bкринж\w*\b|\bcringe\b", "кринж"),
    "имба": (r"\bимб\w*\b", "имба"),
    "жиза": (r"\bжиза\b|\bжизненно\b", "жиза"),
    "рофл": (r"\bрофл\w*\b|\bрофлю\b", "рофл"),
    "вайб": (r"\bвайб\w*\b", "вайб"),
    "хайп": (r"\bхайп\w*\b", "хайп"),
    "лол": (r"\bлол\b|\blol\b", "лол"),
    "жесть": (r"\bжесть\b", "жесть"),
    "капец": (r"\bкапец\b", "капец"),
    "офигеть": (r"\bофиг\w*\b", "офигеть"),
}
SLANG_PATTERNS = {k: re.compile(p, re.I) for k, (p, _) in SAFE_SLANG.items()}
TOPIC_PATTERNS = {
    "therian": re.compile(r"териан|терриан|therian", re.I),
    "dino": re.compile(r"диносьют|диносют|dinosuit|динозавр|dinosaur", re.I),
    "quad": re.compile(r"квадроб|quadrob", re.I),
    "meme": re.compile(r"мем|кринж|лол|имба|видос|рилс|шортс|тикток", re.I),
    "costume": re.compile(r"маск\w*|костюм|cosplay|fursuit", re.I),
    "debate": re.compile(r"баттл|спор|против|кто круче|докажи|сравни", re.I),
}
SERIOUS_WORDS = ("самоуб", "суицид", "смерт", "умер", "травл", "избил", "больниц", "помогите", "мне плохо")
EMAJI = re.compile(r"[\U0001F300-\U0001FAFF]")

def empty():
    return {
        "seen": 0, "short": 0, "questions": 0, "emoji": 0,
        "slang": {}, "topics": {}, "intents": {}
    }

def sanitize(raw):
    if not isinstance(raw, dict):
        return empty()
    safe = empty()
    for key in ("seen", "short", "questions", "emoji"):
        safe[key] = max(0, min(10000, int(raw.get(key, 0) or 0)))
    from offline_brain import TRAINING
    for key, options in (("slang", SAFE_SLANG), ("topics", TOPIC_PATTERNS),
                         ("intents", TRAINING)):
        src = raw.get(key, {})
        if isinstance(src, dict):
            safe[key] = {k: max(0, min(10000, int(v))) for k, v in src.items()
                         if k in options and isinstance(v, (int, float)) and int(v) > 0}
    return safe

def learn(text, prior=None):
    state = sanitize(prior)
    if not isinstance(text, str) or len(text.strip()) < 3:
        return state
    low = text.lower()[:1400]
    # Do not learn from private crises or harassment.
    if any(x in low for x in SERIOUS_WORDS) or any(x in low for x in (
        "сдохни", "убейся", "шлюха", "выследи", "тебя убью", "пошёл нах", "скинь нюдс"
    )):
        return state
    # Bounded aggregate-memory: halve counters to emphasize newer conversation.
    if state["seen"] >= 300:
        for key in ("seen", "short", "questions", "emoji"):
            state[key] //= 2
        for section in ("slang", "topics", "intents"):
            state[section] = {k: v // 2 for k, v in state[section].items() if v >= 2}
    state["seen"] += 1
    state["short"] += int(len(text) <= 110)
    state["questions"] += int("?" in text)
    state["emoji"] += int(bool(EMAJI.search(text)))
    for term, pattern in SLANG_PATTERNS.items():
        if pattern.search(low):
            state["slang"][term] = state["slang"].get(term, 0) + 1
    for term, pattern in TOPIC_PATTERNS.items():
        if pattern.search(low):
            state["topics"][term] = state["topics"].get(term, 0) + 1
    from offline_brain import guess_intent
    intent, confidence = guess_intent(low, state)
    if confidence >= 0.40:
        state["intents"][intent] = state["intents"].get(intent, 0) + 1
    return state

def preferred_style(state):
    state = sanitize(state)
    total = state["seen"]
    if total < 8:
        return {"length": "normal", "emoji": False, "slang": None,
                "top_topic": None, "seen": total}
    ordered = sorted(state["slang"].items(), key=lambda v: (-v[1], v[0]))
    slang = ordered[0][0] if ordered and ordered[0][1] >= 3 else None
    topics = sorted(state["topics"].items(), key=lambda v: (-v[1], v[0]))
    return {
        "length": "short" if state["short"] * 3 >= total * 2 else "normal",
        "emoji": state["emoji"] * 3 >= total,
        "slang": slang,
        "top_topic": topics[0][0] if topics and topics[0][1] >= 4 else None,
        "seen": total,
    }

# Hand-authored insertions, never text copied from users.
SAFE_ENDINGS = {
    "кринж": "Чистый кринж.",
    "имба": "Или это всё-таки имба?",
    "жиза": "Вот это жиза.",
    "рофл": "Рофл или серьёзно?",
    "вайб": "Вот такой вайб.",
    "хайп": "Реальный хайп или пустышка?",
    "лол": "Лол, но факт.",
    "жесть": "Жесть, конечно.",
    "капец": "Капец какой поворот.",
    "офигеть": "Ну офигеть.",
}

def adapt_reply(reply, style, message_id, category):
    """Adjust already safe authored text using aggregate chat trends."""
    if not isinstance(reply, str):
        return ""
    # Safety/moderation replies must not be turned into jokes.
    if category in ("threat", "sexual", "harassment"):
        return reply
    if not style or style.get("seen", 0) < 8:
        return reply
    result = reply.strip()
    if style.get("length") == "short":
        # Short-clause style, but never cut so severely meaning is inverted.
        clauses = re.split(r"(?<=[.!?])\s+", result)
        if len(clauses) > 1 and len(clauses[0]) >= 22:
            result = clauses[0]
    if not style.get("emoji"):
        result = EMAJI.sub("", result).strip()
    slang = style.get("slang")
    # Add only occasionally, with an exact short whitelist.
    if slang in SAFE_ENDINGS and (message_id * 13 + 11) % 5 == 0:
        ending = SAFE_ENDINGS[slang]
        if len(result) + len(ending) <= 240 and ending.lower() not in result.lower():
            result += " " + ending
    return result[:260]
