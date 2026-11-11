import unittest
from datetime import datetime, timezone

from bot import (
    Article, canonical_url, format_post, is_duplicate, normalized_title,
    parse_feed, recent_enough, relevant,
)


class NewsBotTests(unittest.TestCase):
    def test_cyrillic_transliteration(self):
        self.assertEqual(normalized_title("Београд"), "beograd")

    def test_remove_tracking_parameters(self):
        self.assertEqual(
            canonical_url("https://rts.rs/news/?utm_source=x&id=2#section"),
            "https://rts.rs/news?id=2",
        )

    def test_local_filter(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertTrue(relevant(
            Article("RTS", "Cene goriva u Srbiji", "https://rts.rs/a", "", now)
        ))
        self.assertFalse(relevant(
            Article("N1", "New York sports match", "https://n1info.rs/b", "", now)
        ))

    def test_recent_articles(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(recent_enough(
            Article("RTS", "News", "https://rts.rs/1", "", now.timestamp() - 7200), now
        ))
        self.assertFalse(recent_enough(
            Article("RTS", "Old", "https://rts.rs/2", "", now.timestamp() - 36000), now
        ))

    def test_near_duplicate_title(self):
        now = datetime.now(timezone.utc).timestamp()
        a = Article("RTS", "Скупштина Србије донела нови закон", "https://rts.rs/a", "", now)
        state = {
            "seen": {},
            "posted": [{"title_norm": normalized_title(
                "Skupstina Srbije donela novi zakon"
            ), "ts": now}],
        }
        self.assertTrue(is_duplicate(a, state))

    def test_html_escape(self):
        a = Article(
            "RTS", "Original", "https://rts.rs/a?x=2&y=3", "",
            datetime.now(timezone.utc).timestamp(),
        )
        msg = format_post(a, "Тест <b>", "Описание & детали")
        self.assertIn("&lt;b&gt;", msg)
        self.assertIn("&amp;", msg)

    def test_rss_parsing(self):
        rss = b'''<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Cene u Srbiji</title><link>https://example.com/news</link>
        <pubDate>Wed, 11 Nov 2026 14:00:00 GMT</pubDate>
        <description>Nova odluka o cenama.</description></item></channel></rss>'''
        self.assertEqual(len(parse_feed("test", rss)), 1)


if __name__ == "__main__":
    unittest.main()
