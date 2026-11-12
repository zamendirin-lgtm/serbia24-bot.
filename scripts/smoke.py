"""Live feed + automatic translation check without posting to Telegram."""
from datetime import datetime, timezone
import logging

from bot import FreeTranslator, article_photo, fetch_news, recent_enough, relevant, translate_article

logging.basicConfig(level=logging.INFO)
articles = fetch_news()
print("RSS articles:", len(articles))

from collections import Counter

danas_items = [a for a in articles if a.source == "Danas"]
rss_repeats = Counter(a.image_url for a in danas_items if a.image_url)
print("Danas RSS repeated image URLs:", [(url[:130], count) for url, count in rss_repeats.most_common(4) if count > 1])
samples = [a for a in danas_items if any(x in a.title.lower() for x in ("sombor", "zubinom", "policajca", "dosije 23"))]
samples += danas_items[:3]
for sample in samples[:6]:
    print("Danas article:", sample.title[:100])
    print("Danas RSS image:", sample.image_url[:180])
    print("Danas selected photo:", article_photo(sample)[:180])

if not articles:
    raise SystemExit("No RSS articles from any source")
now = datetime.now(timezone.utc)
candidates = [a for a in articles if recent_enough(a, now) and relevant(a)]
print("Fresh relevant articles:", len(candidates))
for item in candidates[:4]:
    url = article_photo(item)
    print("News photo", item.source, bool(url), url[:130])
if not candidates:
    raise SystemExit("No fresh relevant articles")

translator = FreeTranslator()
for a in candidates[:6]:
    try:
        translated, summary = translate_article(a, translator)
        if not translated:
            continue
        print("Success. From:", a.source)
        print("Original:", a.title[:160])
        print("Russian:", translated[:160])
        if summary:
            print("Summary:", summary[:160])
        break
    except Exception as exc:
        print("Translation failed for candidate:", type(exc).__name__)
else:
    raise SystemExit("All translation providers rejected the sample")
