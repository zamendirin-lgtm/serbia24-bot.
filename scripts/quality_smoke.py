"""Live source-to-Russian two-pass QA, NO TELEGRAM REQUESTS.

Checks a complete current public N1 story with the same editorial gates
as scheduled publishing. The script never posts or edits channel history.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from bot import Article, FreeTranslator, translate_article

EXAMPLES = [
    (
        "Danas",
        "Mreža inspektora Srbije reagovala zbog prebacivanja u poresku upravu komunalnog inspektora koji je prijavljivao pritiske",
        "https://www.danas.rs/vesti/ekonomija/mreza-inspektora-srbije-komunalni-inspektor",
    ),
    (
        "N1",
        "Narodna banka Srbije menja pravila za menjačnice",
        "https://n1info.rs/biznis/narodna-banka-srbije-menja-pravila-za-menjacnice",
    ),
]


def main() -> None:
    if not os.getenv("GROQ_API_KEY","").strip():
        raise RuntimeError("No Groq API key; strict 8/10 quality cannot be checked")
    os.environ["EDITOR_REVIEW_ENABLED"]="1"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    successes=[]
    for name,title,url in EXAMPLES:
        article=Article(name,title,url,"",datetime.now(timezone.utc).timestamp())
        try:
            ru_title,body=translate_article(article,FreeTranslator())
            print("QUALITY CHECK ACCEPTED:",name,ru_title)
            print("FINAL TEXT:",body)
            successes.append(True)
        except Exception as exc:
            print("QUALITY CHECK REJECTED:",name,type(exc).__name__,str(exc))
            successes.append(False)
    print("NEWS QUALITY SMOKE:",sum(successes),"/",len(successes),"approved without Telegram posts")
    # Rejected articles are an acceptable editorial safeguard, but at least
    # one complete article must demonstrate the new live threshold.
    if not any(successes):
        raise RuntimeError("No sample cleared the live strict 8/10 quality gate")


if __name__=="__main__":
    main()
