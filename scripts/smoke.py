"""Live RSS + translation smoke test. Never posts to Telegram."""
from datetime import datetime, timezone
import logging
from deep_translator import GoogleTranslator
from bot import fetch_news, recent_enough, relevant, translate_article

logging.basicConfig(level=logging.INFO)
articles = fetch_news()
print("RSS articles:", len(articles))
if not articles:
    raise SystemExit("No RSS articles were fetched from any configured source")
now = datetime.now(timezone.utc)
candidates = [a for a in articles if recent_enough(a, now) and relevant(a)]
print("Fresh relevant articles:", len(candidates))
if not candidates:
    raise SystemExit("No fresh relevant articles, check filter/dates")
translator = GoogleTranslator(source="auto", target="ru")
for a in candidates[:8]:
    try:
        translated, _ = translate_article(a, translator)
        print("Translation works:", translated[:180], "| source:", a.source)
        break
    except Exception as exc:
        print("Translation failed for one candidate:", type(exc).__name__)
else:
    raise SystemExit("Free translation did not work for any sampled article")
