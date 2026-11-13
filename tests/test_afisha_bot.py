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
        self.assertIn("первоисточник", card)
        self.assertNotIn("Бесплатно", card)

    def test_dedupe_by_event_date(self):
        events = parse_jsonld_events(PAGE, URL)
        self.assertEqual(select(events + events, {}, NOW), events)
        self.assertEqual(select(events, {events[0].key: {}}, NOW), [])

    def test_unsafe_event_url(self):
        self.assertFalse(safe_source_url("https://evil.test/event"))
        self.assertFalse(safe_source_url("http://novisad.travel/event"))

    def test_telegram_uses_link_preview(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = response
        self.assertTrue(publish(session, "private-test", "@afisha", "Sample", URL))
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["link_preview_options"]["url"], URL)
        self.assertFalse(payload["link_preview_options"]["is_disabled"])


if __name__ == "__main__":
    unittest.main()
