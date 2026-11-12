"""Live feed + automatic translation check without posting to Telegram."""
from datetime import datetime, timezone
import logging

from bot import FreeTranslator, article_photo, fetch_news, fetch_editorial_paragraphs, recent_enough, relevant, translate_article, rank_news, news_interest_score, MIN_INTEREST_SCORE

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
candidates = rank_news(candidates, now)
print("Fresh relevant articles:", len(candidates))
print("Highest reader-interest picks (no posts):")
for item in candidates[:12]:
    score = news_interest_score(item, now)
    print("Score:", score, "ACCEPT" if score >= MIN_INTEREST_SCORE else "SKIP",
          item.source, item.title[:135])
for item in candidates[:4]:
    url = article_photo(item)
    print("News photo", item.source, bool(url), url[:130])
if not candidates:
    raise SystemExit("No fresh relevant articles")

print("Editorial extraction by source (no Telegram posts):")
for source in ("RTS", "N1", "Danas", "B92"):
    available = [a for a in candidates if a.source == source]
    if not available:
        print(source, ": no matching fresh articles")
        continue
    good = 0
    for sample in available[:3]:
        blocks = fetch_editorial_paragraphs(sample)
        if blocks:
            print(source, "article:", sample.title[:120])
            print(source, "paragraphs:", len(blocks))
            for i, p in enumerate(blocks, 1):
                print(source, "paragraph", i, ":", p[:240])
            good += 1
            break
    if not good:
        print(source, ": unable to extract factual body from sampled articles")

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
