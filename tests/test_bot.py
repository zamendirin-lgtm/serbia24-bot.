import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from bot import (
    Article, canonical_url, format_post, is_duplicate, normalized_title,
    parse_feed, recent_enough, relevant, post_telegram, prepare_summary, photo_caption, rss_photo,
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


    def test_news_style_branding(self):
        item = Article(
            "RTS", "Cene u Srbiji", "https://rts.rs/a", "",
            datetime.now(timezone.utc).timestamp(),
        )
        post = format_post(item, "Цены в Сербии изменились", "Первая деталь. Вторая деталь. Третья деталь.")
        self.assertIn("<b>Цены в Сербии изменились</b>", post)
        self.assertIn("Сербия 24", post)
        self.assertIn("Источник: RTS", post)
        self.assertIn("\n\n", post)
        self.assertNotIn("https://example.com", post)

    def test_telegram_sends_photo_without_english_page_preview(self):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"ok": True}
        with patch("bot.requests.post", return_value=FakeResponse()) as send:
            post_telegram(
                "Тест", "not-a-real-token", "@testchannel",
                "https://rts.rs/a", "https://rts.rs/photo.jpg", "Подпись по-русски",
            )
            self.assertIn("/sendPhoto", send.call_args.args[0])
            payload = send.call_args.kwargs["json"]
            self.assertEqual(payload["photo"], "https://rts.rs/photo.jpg")
            self.assertEqual(payload["caption"], "Подпись по-русски")
            self.assertNotIn("link_preview_options", payload)

    def test_fallback_disables_page_preview(self):
        class Failure:
            status_code = 400
            def json(self):
                return {"ok": False, "description": "Bad photo"}
        class Success:
            status_code = 200
            def json(self):
                return {"ok": True}
        with patch("bot.requests.post", side_effect=[Failure(), Success()]) as send:
            post_telegram(
                "Тест", "not-a-real-token", "@testchannel",
                "https://rts.rs/a", "https://rts.rs/photo.jpg", "Подпись по-русски",
            )
            self.assertEqual(send.call_count, 2)
            self.assertIn("/sendMessage", send.call_args.args[0])
            self.assertTrue(send.call_args.kwargs["json"]["link_preview_options"]["is_disabled"])

    def test_photo_caption_russian(self):
        item = Article("RTS", "Original", "https://rts.rs/a", "", 0)
        caption = photo_caption(item, "Заголовок", "Первое предложение.")
        self.assertIn("Заголовок", caption)
        self.assertIn("Сербия 24", caption)
        self.assertIn("Источник: RTS", caption)
        self.assertNotIn("Original", caption)

    def test_rss_media_image(self):
        import feedparser
        entry = feedparser.parse("""<rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0">
          <channel><item><title>Test</title><link>https://rts.rs/article</link>
          <media:content url="https://rts.rs/photos/a.jpg" type="image/jpeg"/>
          </item></channel></rss>""").entries[0]
        self.assertEqual(rss_photo(entry, "https://rts.rs/article"), "https://rts.rs/photos/a.jpg")

    def test_long_rss_excerpt_remains_concise(self):
        item = Article("RTS", "Novi zakon", "https://rts.rs/a",
                       "Prva rečenica ima važan podatak o Srbiji. "
                       "Druga rečenica objašnjava šta se promenilo. "
                       "Treća rečenica dodaje konkretnu informaciju.",
                       datetime.now(timezone.utc).timestamp())
        excerpt = prepare_summary(item)
        self.assertIn("Druga rečenica", excerpt)
        self.assertLessEqual(len(excerpt), 420)


if __name__ == "__main__":
    unittest.main()
