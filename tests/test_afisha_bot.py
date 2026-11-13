"""Offline tests for sources, dates, prices, dedupe and Russian Telegram cards."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from afisha_bot import (
    Event, event_price, parse_jsonld_events, list_event_urls, event_in_window,
    select, format_event, parse_date, publish, safe_source_url
)

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=ZoneInfo("Europe/Belgrade"))
URL = "https://novisad.travel/en/kalendar-dogadjaja/sjaj-2026"
PAGE = r"""
<html>
<head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
"name":"Sjaj – international jewellery fair",
"startDate":"2026-11-14T10:00:00+01:00",
"endDate":"2026-11-15T18:00:00+01:00",
"url":"https://novisad.travel/en/kalendar-dogadjaja/sjaj-2026",
"description":"Jewellery and watchmakers exhibit their collections.",
"location":{"@type":"Place","name":"Novosadski sajam",
"address":{"@type":"PostalAddress","addressLocality":"Novi Sad"}},
"offers":{"@type":"Offer","lowPrice":"500","priceCurrency":"RSD"},
"image":"https://novisad.travel/example.jpg"}
</script></head><body><h1>Jewellery fair</h1></body></html>
"""

class AfishaTests(unittest.TestCase):
    def test_jsonld_event_price_city_and_dates(self):
        e = parse_jsonld_events(PAGE, URL)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0].city, "Нови-Сад")
        self.assertEqual(e[0].venue, "Novosadski sajam")
        self.assertEqual(e[0].price, "от 500 дин.")
        self.assertEqual(e[0].start.date().isoformat(), "2026-11-14")
        self.assertTrue(event_in_window(e[0], NOW))

    def test_free_and_unknown_price(self):
        self.assertEqual(event_price({"isAccessibleForFree": True}, ""), "Бесплатно (по данным организатора)")
        self.assertEqual(event_price({}, "Ulaz je slobodan."), "Бесплатно (по данным источника)")
        self.assertEqual(event_price({}, "An exhibition of 300 works"), "не указана")
        self.assertEqual(event_price({"offers": {"price": "800", "priceCurrency": "RSD"}}, ""), "800 дин.")

    def test_does_not_infer_from_zero_unrelated(self):
        self.assertEqual(event_price({}, "20 years 10 artists, exhibitions begin at 18:00"), "не указана")

    def test_rejects_missing_or_past_date(self):
        self.assertEqual(parse_jsonld_events(PAGE.replace("2026-11-14T10:00:00+01:00","invalid"), URL), [])
        old = Event(URL, "Old", "Нови-Сад", "", datetime(2026, 10, 1, tzinfo=NOW.tzinfo))
        self.assertFalse(event_in_window(old, NOW))

    def test_ongoing_exhibition(self):
        running = Event(URL, "Show", "Нови-Сад", "",
                        datetime(2026, 10, 1, tzinfo=NOW.tzinfo),
                        datetime(2026, 11, 22, tzinfo=NOW.tzinfo))
        self.assertTrue(event_in_window(running, NOW))

    def test_list_event_links_only(self):
        html = f"""<div class="tribe-events-calendar-list__event-row">
          <h3 class="tribe-events-calendar-list__event-title"><a href="{URL}">Event</a></h3>
          <a href="https://evil.test/a">Ad</a>
          <h3 class="tribe-events-calendar-list__event-title"><a href="{URL}?utm=1">Dup</a></h3>
          </div>"""
        self.assertEqual(list_event_urls(html), [URL])

    def test_no_invented_price_or_false_free(self):
        e = parse_jsonld_events(PAGE.replace('"offers":{"@type":"Offer","lowPrice":"500","priceCurrency":"RSD"},', ''), URL)[0]
        self.assertEqual(e.price, "не указана")
        card = format_event(e, "Выставка ювелирных изделий", "Ювелиры покажут свои работы.")
        self.assertIn("Выставка ювелирных изделий", card)
        self.assertIn("не указана", card)
        self.assertIn("<b>Цена:</b> не указана", card)
        self.assertIn("14.11.2026–15.11.2026", card)
        self.assertIn("Нови-Сад", card)
        self.assertIn("<b>Город:</b> Нови-Сад", card)
        self.assertIn("<b>Место проведения:</b> Novosadski sajam", card)
        self.assertNotIn("Нови-Сад · ", card)
        self.assertIn("Подробности и билеты", card)
        self.assertNotIn("ℹ️ Время и цену проверьте", card)
        self.assertNotIn("Бесплатно", card)

    def test_fabrika_venue_has_verified_address(self):
        e = parse_jsonld_events(PAGE, URL)[0]
        from dataclasses import replace
        e = replace(e, venue="SKCNS Fabrika")
        card = format_event(e, "Фестиваль", "На сцене выступят музыкальные коллективы.")
        self.assertIn("Место проведения:</b> SKCNS Fabrika", card)
        self.assertIn("Bulevar despota Stefana 5", card)

    def test_separate_links_when_real_tickets_available(self):
        from dataclasses import replace
        item = parse_jsonld_events(PAGE, URL)[0]
        only_details = format_event(item, "Выставка украшений", "На выставке представят украшения ювелиров.")
        self.assertIn(">Подробности</a>", only_details)
        self.assertNotIn("Купить билеты", only_details)
        with_tickets = replace(item, ticket_url="https://tickets.rs/event/sjaj_2026_123")
        text = format_event(with_tickets, "Выставка украшений", "На выставке представят украшения ювелиров.")
        self.assertIn(">Подробности</a>", text)
        self.assertIn('href="https://tickets.rs/event/sjaj_2026_123">Купить билеты</a>', text)
        self.assertNotIn("Подробности и билеты", text)

    def test_ticket_link_only_when_explicitly_labeled(self):
        from afisha_bot import find_ticket_link, safe_ticket_url
        from bs4 import BeautifulSoup
        html = '<main><a href="/en/kalendar-dogadjaja/sjaj-2026">Tickets</a><a href="https://tickets.rs/event/sjaj_2026">Kupi kartu</a></main>'
        self.assertEqual(find_ticket_link(BeautifulSoup(html, "html.parser"), {}, URL),
                         "https://tickets.rs/event/sjaj_2026")
        html = '<main><a href="/en/kalendar-dogadjaja/sjaj-2026">More details</a><span>Tickets available</span></main>'
        self.assertEqual(find_ticket_link(BeautifulSoup(html, "html.parser"), {}, URL), "")
        self.assertEqual(safe_ticket_url("https://tickets.rs/", URL), "")
        self.assertEqual(safe_ticket_url("http://tickets.rs/event/test", URL), "")

    def test_dedupe_by_event_date(self):
        events = parse_jsonld_events(PAGE, URL)
        self.assertEqual(select(events + events, {}, NOW), events)
        self.assertEqual(select(events, {events[0].key: {}}, NOW), [])

    def test_unsafe_event_url(self):
        self.assertFalse(safe_source_url("https://evil.test/event"))
        self.assertFalse(safe_source_url("http://novisad.travel/event"))

    def test_telegram_never_generates_source_preview(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = response
        self.assertTrue(publish(session, "private-test", "@afisha", "Sample", URL))
        payload = session.post.call_args.kwargs["json"]
        self.assertTrue(payload["link_preview_options"]["is_disabled"])
        self.assertTrue(session.post.call_args.args[0].endswith("/sendMessage"))

    def test_official_poster_uses_send_photo_and_russian_caption(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = response
        poster = "https://novisad.travel/wp-content/uploads/2019/05/To-Be-Punk-festival-2026_1.jpeg"
        self.assertTrue(publish(session, "private-test", "@afisha",
                                "<b>Панк-фестиваль</b>", URL, poster))
        payload = session.post.call_args.kwargs["json"]
        self.assertTrue(session.post.call_args.args[0].endswith("/sendPhoto"))
        self.assertEqual(payload["photo"], poster)
        self.assertIn("Панк-фестиваль", payload["caption"])
        self.assertNotIn("link_preview_options", payload)

    def test_untrusted_poster_falls_back_to_no_preview_text(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = response
        self.assertTrue(publish(session, "private-test", "@afisha", "Sample",
                                URL, "https://example.com/poster.jpg"))
        self.assertTrue(session.post.call_args.args[0].endswith("/sendMessage"))
        self.assertTrue(session.post.call_args.kwargs["json"]["link_preview_options"]["is_disabled"])


if __name__ == "__main__":
    unittest.main()
