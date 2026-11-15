"""Review the real Danas national arts pension story with both AI passes.

This never posts to Telegram. It verifies readers see what the awards are
and what actually changed (five vs ten minister nominees).
"""
from __future__ import annotations

import os
from unittest.mock import patch
import editorial
from datetime import datetime, timezone

from bot import (
    Article, FreeTranslator, fetch_editorial_paragraphs, translate_article,
)
from editorial import ensure_cultural_award_is_explained

URL = "https://www.danas.rs/kultura/selakovic-nacionalne-penzije-boskovic-savin-kovacevic/"
TITLE = (
    "Selakoviću proširena ovlašćenja za nacionalne penzije: "
    "Ministarstvo ranije odbilo Bošković, Savina i Kovačevića"
)

def main() -> None:
    if not os.getenv("GROQ_API_KEY", "").strip():
        raise RuntimeError("Groq API key not configured")

    # Two-stage editorial review explicitly enabled in the smoke test.
    os.environ["EDITOR_REVIEW_ENABLED"] = "1"
    article = Article(
        "Danas", TITLE, URL, "",
        datetime.now(timezone.utc).timestamp(),
    )
    paragraphs = fetch_editorial_paragraphs(article)
    if len(paragraphs) < 2:
        raise RuntimeError("Original article extraction failed")
    print("Selected source paragraphs:", len(paragraphs))
    print("Source contains old-new comparison:",
          any("pet" in p.lower() and "deset" in p.lower() for p in paragraphs))

    basic = editorial._basic_checks
    def traced_checks(title, paragraphs, factual_input, **kwargs):
        try:
            return basic(title, paragraphs, factual_input, **kwargs)
        except Exception as exc:
            print("News candidate rejected because:", type(exc).__name__, str(exc))
            print("Candidate title:", title)
            print("Candidate text:", " ".join(paragraphs))
            raise

    with patch.object(editorial, "_basic_checks", side_effect=traced_checks):
        title, body = translate_article(article, FreeTranslator())
    ensure_cultural_award_is_explained(title, body.split("\n\n"), TITLE + " " + " ".join(paragraphs))
    if "пожизнен" not in body.lower() or "выплат" not in body.lower():
        raise RuntimeError("National cultural awards were not explained")
    print("Two-stage Groq review passed: no Telegram publication")
    print("Accepted headline:", title)
    print("Accepted body:", body)

if __name__ == "__main__":
    main()
