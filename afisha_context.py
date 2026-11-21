"""Strictly source-supported age and performance-language labels for Afisha.

Do not infer age restrictions, accessibility or spoken language from the
performer's name, location or the mere fact that a show is for children.
"""
from __future__ import annotations

import re


def age_label(text: str) -> str:
    source = str(text or "").casefold()
    # "za decu uzrasta od 3 do 12 godina"
    ages = re.search(
        r"(?:uzrast[a-z]*|decu\s+od|deca\s+od|ages?\s*)(?:\s+od)?\s*"
        r"(\d{1,2})\s*(?:do|[-–])\s*(\d{1,2})\s*(?:godina|years?)?",
        source,
    )
    if ages:
        lo, hi = int(ages.group(1)), int(ages.group(2))
        if 0 <= lo < hi <= 99:
            return f"{lo}–{hi} лет (по информации организатора)"
    minimum = re.search(
        r"(?:za\s+decu|deca|uzrast[a-z]*|ages?\s*|odrasli)"
        r".{0,30}?\b(?:od\s+)?(\d{1,2})\s*(?:\+|godina|years?)",
        source,
    )
    if minimum:
        age = int(minimum.group(1))
        if 0 <= age <= 21:
            return f"от {age} лет (по информации организатора)"
    restricted = re.search(r"(?<!\d)18\+\s*(?:godina|only|publika|audience)?\b", source)
    if restricted:
        return "18+ (по информации организатора)"
    return ""


def language_label(text: str) -> str:
    source = str(text or "").casefold()
    explicit = (
        (r"\bna\s+srpskom(?:\s+(?:jeziku|govornom|titlovima))?\b|"
         r"\b(?:jezik|izvođenj[ea])\s*[:–-]\s*srpski\b|"
         r"\bsinhronizovan[a-z]*\s+na\s+srpski", "сербский"),
        (r"\bna\s+engleskom(?:\s+jeziku)?\b|"
         r"\b(?:jezik|izvođenj[ea])\s*[:–-]\s*engleski\b|"
         r"\bin\s+english\b", "английский"),
        (r"\bna\s+ruskom(?:\s+jeziku)?\b|"
         r"\b(?:jezik|izvođenj[ea])\s*[:–-]\s*ruski\b|"
         r"\bin\s+russian\b", "русский"),
    )
    found = [label for pattern, label in explicit if re.search(pattern, source, re.I)]
    return found[0] if len(found) == 1 else ""


def contextual_lines(event) -> list[str]:
    # Only event-specific factual description, not extrapolated venue language.
    text = str(event.description or "")
    result = []
    age = age_label(text)
    language = language_label(text)
    if age:
        result.append("👨‍👩‍👧 <b>Возраст:</b> " + age)
    if language:
        result.append("🗣 <b>Язык:</b> " + language)
    return result
