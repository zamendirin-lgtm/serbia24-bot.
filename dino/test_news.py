"""No-network news validation before any live Telegram post."""
import news_auto as n
from datetime import datetime, timezone

def main():
    assert len(n.CURATED) >= 2
    for story in n.CURATED:
        assert n.source_is_valid(story["url"])
        assert n.relevant_story(story["title"], story["summary"]) or story["key"].startswith("unsw-")
        assert len(story["summary"]) >= 100
        assert story["published"] and story["type"]
    assert not n.relevant_story("Новость!", "")
    assert not n.relevant_story("Сенсация с подростком", "тест " * 35)
    assert n.suitable_rights({"LicenseShortName":{"value":"CC0"}})["credit"] == ""
    assert n.suitable_rights({"LicenseShortName":{"value":"All rights reserved"}}) is None
    state = {}
    old_discovery = n.discover_rss
    n.discover_rss = lambda now: []
    try:
        first = n.choose_news(state, datetime.now(timezone.utc))
        assert first and first["key"] == n.CURATED[0]["key"]
        assert n.publish_news(state, datetime.now(timezone.utc), dry_run=True)
        assert not state.get("posted_news"), "dry-run should never mark stories posted"
        state["posted_news"] = [x["key"] for x in n.CURATED]
        assert n.choose_news(state, datetime.now(timezone.utc)) is None
    finally:
        n.discover_rss = old_discovery
    print("NEWS_TESTS_OK", len(n.CURATED), "verified curated stories")

if __name__ == "__main__":
    main()
