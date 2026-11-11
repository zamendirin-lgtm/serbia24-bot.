"""Live RSS + public translation provider test. Never posts to Telegram."""
from datetime import datetime, timezone
import logging
import requests
from deep_translator import GoogleTranslator
from bot import fetch_news, recent_enough, relevant, translate_article

logging.basicConfig(level=logging.INFO)
articles = fetch_news()
print("RSS articles:", len(articles))
if not articles:
    raise SystemExit("No RSS articles from any configured source")
now = datetime.now(timezone.utc)
candidates = [a for a in articles if recent_enough(a, now) and relevant(a)]
print("Fresh relevant articles:", len(candidates))
if not candidates:
    raise SystemExit("No fresh relevant articles")
sample = candidates[0]
print("Serbian sample:", sample.title[:150])
print("Checking MyMemory direct sr|ru...")
resp = requests.get(
    "https://api.mymemory.translated.net/get",
    params={"q": sample.title[:190], "langpair": "sr|ru"},
    timeout=15,
)
print("MyMemory HTTP:", resp.status_code)
print("MyMemory preview:", resp.text[:500])
print("Checking alternate no-key Google endpoint...")
resp2 = requests.get(
    "https://translate.googleapis.com/translate_a/t",
    params={"client": "dict-chrome-ex", "sl": "sr", "tl": "ru", "q": sample.title[:190]},
    timeout=15,
)
print("Google alternate HTTP:", resp2.status_code)
print("Google alternate preview:", resp2.text[:300])
