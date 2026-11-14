"""Small offline language-understanding layer for DinoDvij.

Trains a bag-of-words Naive Bayes intent classifier on *synthetic examples*
at import time. It runs on the GitHub Actions CPU with no paid model, no
network calls, and no collection of individual training examples from users.
It composes a short contextual response from hand-reviewed safe fragments;
live chat only adjusts aggregate topic, intent and style frequencies.
This is deliberately NOT a generative LLM.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import math
import random
import re

# All examples here are original, invented training utterances.
TRAINING = {
    "question": [
        "почему эта маска так популярна", "как сделать костюм своими руками",
        "где купить хвост для маски", "когда будет новый ролик",
        "кто придумал этот тренд", "что лучше смотреть сегодня",
        "а это вообще как работает", "сколько стоит динозавр костюм",
        "чем отличается новый образ", "можно ли такое повторить",
        "как вы снимаете такие видео", "какой образ выбрать",
        "зачем нужен этот аксессуар", "почему всем нравится такой танец",
        "кто будет первым в баттле", "реально ли это крутой костюм",
    ],
    "debate": [
        "диносьюты круче масок", "нет террианы лучше всех",
        "давай спорить кто победит", "я вообще не согласен",
        "этот тренд лучше другого", "не так все это фигня",
        "спорим что мой вариант круче", "твой аргумент слабоват",
        "у меня противоположное мнение", "докажи что это лучше",
        "не верю что это хайп", "маски проигрывают костюмам",
        "серьёзно считаешь это топом", "давай сравним два образа",
        "этот подход полный кринж", "нет это имба а не кринж",
    ],
    "joke": [
        "ахаха я умираю от смеха", "лол это реально смешно",
        "костюм застрял в двери", "динозавр против дверного проема",
        "рофл ну и мем", "кринж но смешно",
        "я упал со смеху", "чисто мемная ситуация",
        "это шутка если что", "поржал с нового видоса",
        "как же я ржу", "хахаха вот это поворот",
        "обожаю тупые мемы", "фейл года просто",
        "это видео меня добило", "блин смешно получилось",
    ],
    "showcase": [
        "смотрите мой новый костюм", "оцените мою маску",
        "я сделал динозавра своими руками", "мой новый образ готов",
        "посмотрите что я снял", "выложил новый ролик",
        "оцени рисунок маски", "вот моя работа",
        "сняли новый танец", "я сам это придумал",
        "показываю свой новый хвост", "моя поделка готова",
        "зацените мой видос", "у меня получилось повторить",
        "я переделал костюм", "как вам моя маска",
    ],
    "opinion": [
        "мне нравится такая эстетика", "по моему это очень красиво",
        "этот костюм выглядит ярко", "я считаю что это стиль",
        "не люблю этот тренд", "по мне так старый вариант лучше",
        "мне кажется выглядит странно", "думаю это хороший видос",
        "обожаю маски животных", "я бы выбрал зелёного динозавра",
        "честно мне больше нравится другое", "у меня своё мнение",
        "выглядит немного странно", "я люблю такой вайб",
        "по моему прикольно", "для меня это слишком громко",
    ],
    "greeting": [
        "всем привет", "привет чат", "хай всем",
        "хеллоу народ", "как дела у всех",
        "что нового здесь", "здарова люди",
        "я только пришёл", "добрый вечер всем",
        "зашёл посмотреть что происходит", "ку ку",
        "здрасьте я тут", "народ вы тут", "что происходит в чате",
        "всем доброго дня", "давно меня не было",
    ],
    "reaction": [
        "это просто имба", "ого какой хайп",
        "вот это да очень круто", "капец вот это поворот",
        "вау это мощно", "мне зашло просто огонь",
        "жесть как красиво", "офигеть вот это образ",
        "видео реально залетело", "вот это номер",
        "ну вообще отлично получилось", "не ожидал такого",
        "сильный ход", "это эпик", "выглядит бомбически",
        "реально впечатляет",
    ],
}

TOKEN_PATTERN = re.compile(r"[а-яёa-z]{2,24}", re.I)
NOISE = {"это", "этот", "так", "такой", "такая", "мне", "мой", "моя",
         "твой", "вот", "для", "или", "тут", "всё", "просто", "чтобы",
         "есть", "всем", "можно", "очень", "когда", "сейчас"}

TOPICS = {
    "therian": "маски и терианы",
    "dino": "диносьюты",
    "quad": "квадробика",
    "meme": "мемы и видео",
    "costume": "образы и костюмы",
    "debate": "спор в чате",
}
BASES = {
    "question": (
        "Хм, {topic}. Вопрос хороший, а вот с ответом всё не так просто.",
        "Так, {topic} снова вызывают вопросы. У кого есть пруфы?",
        "Вот здесь без деталей не разобраться. Какой вариант ты сам считаешь нормальным?",
        "А вот это уже интересный вопрос. Кто в теме, объясните без воды?",
    ),
    "debate": (
        "Вот и приехали: {topic} снова разделили чат. Аргументы в студию 💀",
        "Вижу громкий тейк. Ты уверен или это чисто ради хайпа?",
        "Спорить можно. Но пока это больше эмоции, чем доказательства 😈",
        "Ого, баттл пошёл. Только не подменяйте факты капслоком.",
    ),
    "joke": (
        "АХАХ, вот это уже годный сюжет для мема 💀",
        "Погодите, то есть это реально произошло? Вот это рофл 😂",
        "Ну всё, интернет опять переиграл сам себя.",
        "Вот за такие моменты я и люблю этот хаос в чате 🍿",
    ),
    "showcase": (
        "О, свой контент подъехал. Что скажете, чат: стиль или кринж?",
        "Вот это уже интереснее бесконечных споров. Кто бы такое повторил?",
        "За попытку — зачёт. А что бы вы добавили к этому образу?",
        "Хм, {topic}. Есть интересная идея, но давайте оценивать саму работу, не автора.",
    ),
    "opinion": (
        "Ну, позиция понятна. А противоположная сторона что скажет? 🍿",
        "Это мнение смелое. Кто готов нормально поспорить?",
        "Нормальный тейк, хотя я бы не спешил объявлять победителя.",
        "Вот тут соглашаться необязательно. Вкусы — отдельный баттл.",
    ),
    "greeting": (
        "О, чат ожил. Ну что, чем сегодня удивите? 🦖",
        "Здарова. Где годные мемы и новые ролики?",
        "Народ в сборе? А то тут скоро снова будет спор века.",
    ),
    "reaction": (
        "Вот это мощно. Интересно, хайп выдержит хотя бы до завтра? 😈",
        "Окей, тут даже мне сложно придраться. Почти.",
        "Ну всё, новая имба в чате. Или опять два дня хайпа?",
        "Тут либо легенда, либо эпичный рофл. Третьего не дано.",
    ),
}


def tokens(text):
    if not isinstance(text, str):
        return []
    return [t for t in TOKEN_PATTERN.findall(text.lower()[:900])
            if t not in NOISE]


@lru_cache(maxsize=1)
def trained_model():
    category_counts = {}
    vocabulary = set()
    doc_counts = {}
    frequencies = {}
    for kind, examples in TRAINING.items():
        counts = Counter()
        for example in examples:
            counts.update(tokens(example))
        category_counts[kind] = sum(counts.values())
        frequencies[kind] = counts
        doc_counts[kind] = len(examples)
        vocabulary.update(counts)
    return category_counts, vocabulary, doc_counts, frequencies


def guess_intent(text, aggregate=None):
    """Small Naive Bayes classifier; returns (intent, approximate confidence).

    Confidence is relative probability among hand-authored intent categories,
    not a calibrated probability of actual message correctness.
    """
    words = tokens(text)
    if not words:
        return "opinion", 0.0
    totals, vocab, docs, term_counts = trained_model()
    usable = [w for w in words if w in vocab]
    if not usable:
        return "opinion", 0.0
    n_docs = sum(docs.values())
    score = {}
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    priors = aggregate.get("intents", {})
    if not isinstance(priors, dict):
        priors = {}
    for intent, counts in term_counts.items():
        # Only tiny prior adjustment from aggregate chat-style frequency.
        prior = min(10, int(priors.get(intent, 0) or 0))
        p = (docs[intent] + 0.15 * prior) / (n_docs + 0.15 * sum(
            min(10, int(priors.get(c, 0) or 0)) for c in docs
        ))
        val = math.log(p)
        for word in usable:
            val += math.log((counts[word] + 1.0) /
                            (totals[intent] + len(vocab)))
        score[intent] = val
    best = max(score, key=score.get)
    # Log-sum-exp avoids overflow for unusual very long messages.
    highest = max(score.values())
    denominator = sum(math.exp(v - highest) for v in score.values())
    confidence = math.exp(score[best] - highest) / denominator
    return best, round(confidence, 3)


def topic_in_text(text, style):
    from learn_style import TOPIC_PATTERNS
    for topic, pattern in TOPIC_PATTERNS.items():
        if pattern.search(text[:600]):
            return topic
    # Fall back to a popular aggregate theme, not to any person's history.
    preferred = style.get("top_topic") if isinstance(style, dict) else None
    return preferred if preferred in TOPICS else "debate"


def compose(text, msg_id, style=None, tone="banter"):
    """Generate a context-aware but constrained original response."""
    if style is None:
        style = {}
    intent, confidence = guess_intent(text, style)
    # Avoid forcing an interpretation on a totally unfamiliar message.
    if confidence < 0.20:
        intent = "opinion"
    # User asks for a roast/battle explicitly; don't lose that mode.
    if tone == "roast":
        intent = "debate"
    elif tone == "battle":
        intent = "debate"
    topic = topic_in_text(text, style)
    rng = random.Random(msg_id * 11400714819323198485)
    choices = BASES.get(intent, BASES["opinion"])
    template = rng.choice(choices)
    reply = template.replace("{topic}", TOPICS[topic])
    # For a user explicitly talking to the bot, never fake knowledge.
    return reply[:250], {"intent": intent, "confidence": confidence, "topic": topic}
