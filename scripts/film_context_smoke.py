"""No-post regression against an actual public N1 documentary interview.

This runs with the configured API secret and NEVER sends to Telegram.
If the post does not name the film, the editorial gate should reject it.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from bot import Article, FreeTranslator, fetch_editorial_paragraphs, translate_article
from context_guard import ensure_resolved_context

URL = "https://n1info.rs/vesti/kikic-dokumentarac-rudarenje-istocna-srbija"
TITLE = ("Kikić pred premijeru dokumentarca o rudarenju u istočnoj Srbiji: "
         "Kapital stranog investitora ne sme biti prioritet")


def main() -> None:
    if not os.getenv("GROQ_API_KEY", "").strip():
        print("Groq key not available for actual film story quality check")
        return
    article = Article(
        "N1", TITLE, URL, "",
        datetime.now(timezone.utc).timestamp(),
    )
    source = fetch_editorial_paragraphs(article)
    if not source:
        raise RuntimeError("Could not extract factual source paragraphs")
    print("Original article paragraphs:", len(source))
    print("Source supplies documentary title:",
          any("Kineska četvrt" in paragraph for paragraph in source))
    if not any("Kineska četvrt" in paragraph for paragraph in source):
        raise RuntimeError("Original documentary title was lost before AI rewriting")

    ru_title, ru_body = translate_article(article, FreeTranslator())
    ensure_resolved_context(ru_title, ru_body.split("\n\n"))
    print("Accepted Russian film article headline:", ru_title)
    print("Accepted Russian film article prose:", ru_body)
    print("Film identity preserved: yes; Telegram publication: NO")


if __name__ == "__main__":
    main()
