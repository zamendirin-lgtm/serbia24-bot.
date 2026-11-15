"""No-post full editorial QA for the Nov 2026 NBS 30/60-day rule.

The final Russian news post MUST explain the 14-day, 10% condition.
Never send it to Telegram, and do not print secrets or request headers.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from bot import (
    Article, FreeTranslator, fetch_editorial_paragraphs,
    translate_article,
)
from editorial import ensure_conditional_rules_explained


SOURCE_URL = "https://n1info.rs/biznis/narodna-banka-srbije-menja-pravila-za-menjacnice/"
SOURCE_TITLE = "Narodna banka Srbije menja pravila za menjačnice"


def main() -> None:
    if not os.getenv("GROQ_API_KEY", "").strip():
        raise RuntimeError("Groq key not configured for real NBS editorial QA")

    article = Article(
        "N1", SOURCE_TITLE, SOURCE_URL, "",
        datetime.now(timezone.utc).timestamp(),
    )
    excerpts = fetch_editorial_paragraphs(article)
    if len(excerpts) < 2:
        raise RuntimeError("N1 article extraction lacks factual paragraphs")

    source = SOURCE_TITLE + " " + " ".join(excerpts)
    if not (
        re.search(r"\b30\s+dana\b", source, re.I)
        and re.search(r"\b60\s+dana\b", source, re.I)
        and re.search(r"\b14\s+dana\b", source, re.I)
        and re.search(r"\b10\s*(?:odsto|posto|%)\b", source, re.I)
    ):
        raise RuntimeError("Important 30/60/14-day or 10% conditions lost by extraction")

    title, text = translate_article(article, FreeTranslator())
    ensure_conditional_rules_explained(title, text.split("\n\n"), source)

    print("Full NBS 30/60-day article quality check: passed")
    print("Accepted headline:", title)
    print("Accepted body:", text)
    print("Contains both deadlines and actual 14-day / 10% exception; NO POSTING")


if __name__ == "__main__":
    main()
