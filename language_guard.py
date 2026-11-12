"""Safety gate: never publish Serbian text as a Russian news article.

Serbian and Russian both use Cyrillic. Detect the *language*, not just the
alphabet. Reject questionable output rather than silently mislabeling it.
"""
from __future__ import annotations

import re
from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0

# Serbian Cyrillic letters absent from normal Russian spelling.
SERBIAN_ONLY = re.compile(r"[ђЂјЈљЉњЊћЋџЏ]")

# Short Serbian function words/specific vocabulary, especially useful when
# text has been force-transliterated to Russian Cyrillic alphabet.
SERBIAN_WORDS = frozenset((
    "је", "није", "су", "се", "ће", "смо", "сви", "сва", "због",
    "који", "које", "која", "њих", "каже", "оптужује", "ухапсила",
    "приведен", "удружења", "грађана", "изјавио", "изјавила",
    "покренута", "саопштила", "саопштењу", "тужилаштва",
))
# Distinctive Russian function words and newspaper verbs.
RUSSIAN_WORDS = frozenset((
    "что", "который", "которая", "которые", "которых", "его",
    "её", "их", "также", "этот", "эта", "это", "этом", "эти",
    "был", "была", "были", "будет", "будут", "для", "если",
    "после", "перед", "между", "поэтому", "согласно",
    "сообщил", "сообщила", "сообщили", "поскольку",
    "полиция", "прокуратура", "власти", "правительство",
    "задержали", "задержала", "расследование", "причиной",
    "полагают", "отметил", "отметила", "отметили",
    "заявил", "заявила", "заявили", "рассказал", "рассказала",
))


class WrongLanguageError(ValueError):
    """News text is not reliably Russian."""


def _language_probability(text: str) -> float:
    try:
        return next((v.prob for v in detect_langs(text) if v.lang == "ru"), 0.0)
    except LangDetectException:
        return 0.0


def ensure_russian(title: str, paragraphs: list[str] | tuple[str, ...]) -> None:
    """Check complete caption and each long paragraph; fail closed.

    The model can make a short headline without many Russian stopwords, so
    do not require language-detector certainty for *headline alone*.
    """
    texts = [title, *paragraphs]
    if any(SERBIAN_ONLY.search(t or "") for t in texts):
        raise WrongLanguageError("Сербская кириллица в тексте новости")

    # Avoid ASCII/Serbian Latin summaries masquerading as Russian.
    def letters(text: str) -> tuple[int, int]:
        cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
        latin = len(re.findall(r"[a-zA-ZčćđšžČĆĐŠŽ]", text))
        return cyr, latin

    for index, text in enumerate(paragraphs):
        cyr, latin = letters(text)
        if cyr < 45:
            raise WrongLanguageError(f"Абзац {index + 1} слишком короткий или не на русском")
        if latin > max(24, cyr // 3):
            raise WrongLanguageError(f"Абзац {index + 1} содержит иностранный текст")

    combined = "\n".join(paragraphs)
    tokens = re.findall(r"[а-яёА-ЯЁ]+", combined.lower())
    distinct_serbian = sum(word in SERBIAN_WORDS for word in tokens)
    distinct_russian = sum(word in RUSSIAN_WORDS for word in tokens)

    if distinct_serbian >= 2 and distinct_serbian >= distinct_russian:
        raise WrongLanguageError("Обнаружены сербские слова, а не русский перевод")
    if _language_probability(combined) < 0.78:
        raise WrongLanguageError("Русский язык в тексте не подтверждён")

    for i, paragraph in enumerate(paragraphs, 1):
        # Long enough for reliable n-gram classification. Brief quotes are
        # too short; all still pass script and Russian combined-text checks.
        if len(paragraph) >= 115 and _language_probability(paragraph) < 0.65:
            raise WrongLanguageError(f"Абзац {i} не подтверждён как русский")
