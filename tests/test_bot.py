import unittest
from unittest.mock import Mock
from datetime import timedelta
from unittest.mock import patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot import (
    Article, canonical_url, format_post, is_duplicate, normalized_title,
    parse_feed, recent_enough, relevant, post_telegram, prepare_summary, photo_caption, rss_photo, normal_image_url,
    same_event_title, event_terms, prune_state, publication_allowed,
    image_dhash, photo_url_key, is_repeated_photo,
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

    def test_spain_news_is_not_serbian_news(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertFalse(relevant(
            Article("Danas",
                    "Veliki protesti širom Španije zbog problema sa stanovanjem, samo u Madridu 120.000 ljudi",
                    "https://www.danas.rs/a",
                    "U Srbiji se takođe govori o protestima i pravima građana.", now)
        ))

    def test_serbian_story_quoting_foreign_media_is_local(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertTrue(relevant(
            Article("N1", "Američki časopis o pobedi studenata u Srbiji",
                    "https://n1info.rs/a", "", now)
        ))

    def test_no_night_publications_belgrade_winter(self):
        zone = ZoneInfo("Europe/Belgrade")
        for hour in (22, 23, 0, 1, 7):
            local = datetime(2026, 11, 12 if hour > 7 else 13, hour, 30, tzinfo=zone)
            self.assertFalse(publication_allowed(local), f"should block {hour}")
        for hour in (8, 9, 21):
            local = datetime(2026, 11, 12, hour, 30, tzinfo=zone)
            self.assertTrue(publication_allowed(local), f"should permit {hour}")

    def test_no_night_publications_belgrade_summer(self):
        zone = ZoneInfo("Europe/Belgrade")
        for hour in (0, 7, 22, 23):
            self.assertFalse(publication_allowed(datetime(2026, 7, 12, hour, 0, tzinfo=zone)))
        for hour in (8, 20, 21):
            self.assertTrue(publication_allowed(datetime(2026, 7, 12, hour, 0, tzinfo=zone)))

    def test_trump_iran_not_serbia(self):
        a = Article("N1",
            "Tramp: SAD nisu započele rat sa Iranom, Teheran vodi rat protiv Amerike",
            "https://n1info.rs/iran", "Donald Trump je izjavio.", 0)
        self.assertFalse(relevant(a))

    def test_nis_is_not_nisu(self):
        a = Article("N1", "U Nišu počela izgradnja nove bolnice",
                    "https://n1info.rs/nis", "", 0)
        self.assertTrue(relevant(a))
        unrelated = Article("N1", "Političari nisu zadovoljni novim izborima u Francuskoj",
                            "https://n1info.rs/a", "", 0)
        self.assertFalse(relevant(unrelated))

    def test_kosovo_local_protest_excluded(self):
        a = Article("Danas",
            "U Zubinom Potoku na severu Kosova protest porodica uhapšenih Srba u slučaju Dosije 23",
            "https://www.danas.rs/kosovo", "U Srbiji su svi pratili vest", 0)
        self.assertFalse(relevant(a))

    def test_kosovo_official_serbian_statement_allowed(self):
        a = Article("RTS", "Vučić o situaciji na Kosovu: Vlada Srbije objavila mere",
                    "https://www.rts.rs/vest", "", 0)
        self.assertTrue(relevant(a))

    def test_summary_discards_source_questions(self):
        a = Article("RTS", "Ekspo u Srbiji", "https://rts.rs/a",
             "Međunarodne manifestacije donose ekonomsku korist. "
             "Međutim, neki građani kritikuju troškove izložbe. "
             "Kako za 93 dana predstaviti Srbiju i privući turiste?", 0)
        summary = prepare_summary(a)
        self.assertNotIn("Kako za", summary)
        self.assertNotIn("?", summary)
        self.assertIn("Međutim", summary)

    def test_image_identical_pixels_different_file_encodings(self):
        from io import BytesIO
        from PIL import Image
        im = Image.new("RGB", (42, 30), "white")
        for y in range(12):
            for x in range(26):
                im.putpixel((x, y), (20, 30, 70))
        a = BytesIO()
        b = BytesIO()
        im.save(a, format="PNG")
        im.save(b, format="JPEG", quality=80)
        # JPEG compression can flip one or two dHash bits; near-identical
        # photographs must still count as duplicates.
        distance = (int(image_dhash(a.getvalue()), 16) ^ int(image_dhash(b.getvalue()), 16)).bit_count()
        self.assertLessEqual(distance, 3)

    def test_repeated_photo_url_and_hash(self):
        now = datetime.now(timezone.utc).timestamp()
        url = "https://www.danas.rs/images/interview.png"
        state = {"photos": {photo_url_key(url): now}, "phashes": {"abcda98765ef4321": now}}
        self.assertTrue(is_repeated_photo(url, "", state))
        self.assertTrue(is_repeated_photo(
            "https://www.danas.rs/images/another.jpg", "abcda98765ef4321", state
        ))
        self.assertFalse(is_repeated_photo(
            "https://www.danas.rs/images/new.jpg", "1234567890abcdef", state
        ))

    def test_prune_photo_history(self):
        now = datetime.now(timezone.utc)
        state = {"seen": {}, "posted": [], "photos": {
                    "recent": (now - timedelta(days=15)).timestamp(),
                    "old": (now - timedelta(days=70)).timestamp()},
                 "phashes": {
                    "abcda98765ef4321": (now - timedelta(days=8)).timestamp(),
                    "abcda98765ef4320": (now - timedelta(days=90)).timestamp()}}
        prune_state(state, now)
        self.assertEqual(list(state["photos"]), ["recent"])
        self.assertEqual(list(state["phashes"]), ["abcda98765ef4321"])

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

    def test_duplicate_same_news_different_order(self):
        now = datetime.now(timezone.utc).timestamp()
        previous = Article(
            "RTS", "Drekslmajer zatvara fabriku u Zrenjaninu",
            "https://www.rts.rs/vesti/stara", "", now,
        )
        later = Article(
            "Danas", "U Zrenjaninu kompanija Drekslmajer zatvara fabriku",
            "https://www.danas.rs/vesti/nova", "", now,
        )
        state = {"seen": {}, "posted": [
            {"ts": now, "title_norm": normalized_title(previous.title), "source": "RTS"}
        ]}
        self.assertTrue(is_duplicate(later, state))

    def test_duplicate_same_news_reordered_price_headline(self):
        self.assertTrue(same_event_title(
            normalized_title("Cene goriva u Srbiji povećane od petka"),
            normalized_title("Od petka povećane cene goriva u Srbiji"),
        ))

    def test_cyrillic_vs_latin_duplicate(self):
        self.assertTrue(same_event_title(
            normalized_title("Зрењанин: Дрекслмајер затвара фабрику"),
            normalized_title("Drekslmajer zatvara fabriku u Zrenjaninu"),
        ))

    def test_different_prices_are_not_duplicated(self):
        self.assertFalse(same_event_title(
            normalized_title("Cena dizela u Srbiji 195 dinara"),
            normalized_title("Cena dizela u Srbiji 199 dinara"),
        ))

    def test_denial_is_not_same_as_affirmation(self):
        self.assertFalse(same_event_title(
            normalized_title("Fabrika u Zrenjaninu neće se zatvoriti"),
            normalized_title("Fabrika u Zrenjaninu se zatvoriti"),
        ))

    def test_different_accidents_same_city(self):
        self.assertFalse(same_event_title(
            normalized_title("Saobraćajna nesreća u Beogradu: troje povređeno"),
            normalized_title("Nova saobraćajna nesreća u Beogradu, dve osobe povređene"),
        ))

    def test_similar_topic_but_different_event(self):
        self.assertFalse(same_event_title(
            normalized_title("U Beogradu otvorena nova bolnica"),
            normalized_title("U Beogradu zatvorena nova bolnica"),
        ))

    def test_store_history_60_days(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=45)).timestamp()
        old = (now - timedelta(days=62)).timestamp()
        state = {
            "seen": {"recent": recent, "old": old},
            "posted": [{"ts": recent, "title_norm": "recent"},
                       {"ts": old, "title_norm": "old"}],
        }
        prune_state(state, now)
        self.assertEqual(list(state["seen"]), ["recent"])
        self.assertEqual([item["title_norm"] for item in state["posted"]], ["recent"])

    def test_low_information_titles_not_false_duplicate(self):
        self.assertFalse(same_event_title(
            normalized_title("Novi zakon u Srbiji o porezu"),
            normalized_title("Novi zakon u Srbiji o platama"),
        ))

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
        self.assertNotIn("Сербия 24", post)
        self.assertNotIn("#НовостиСербии", post)
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
        self.assertNotIn("Сербия 24", caption)
        self.assertNotIn("#НовостиСербии", caption)
        self.assertIn("Источник: RTS", caption)
        self.assertNotIn("Original", caption)

    def test_reject_youtube_embed_as_news_photo(self):
        fake = "https://www.youtube.com/embed/XNxSvHuHthQ"
        self.assertEqual(normal_image_url(fake), "")
        import feedparser
        entry = feedparser.parse("""<rss version="2.0"><channel><item>
          <title>U Beogradu uhapšena tri lica</title>
          <link>https://www.danas.rs/vesti/beograd/123</link>
          <description><![CDATA[<iframe src="https://www.youtube.com/embed/XNxSvHuHthQ"></iframe>
          <img src="https://www.youtube.com/embed/XNxSvHuHthQ">]]></description>
          </item></channel></rss>""").entries[0]
        self.assertEqual(rss_photo(entry, "https://www.danas.rs/vesti/beograd/123"), "")

    def test_regular_publisher_photo_still_allowed(self):
        self.assertEqual(
            normal_image_url("https://www.danas.rs/wp-content/uploads/2026/11/photo.jpg"),
            "https://www.danas.rs/wp-content/uploads/2026/11/photo.jpg",
        )

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
