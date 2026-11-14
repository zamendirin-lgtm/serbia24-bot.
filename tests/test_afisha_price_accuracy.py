"""Ensure ticket minimums are not misreported as universal admission prices."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from afisha_bot import format_event, publish
from belgrade_events import parse_belgrade_cards

NOW = datetime(2026, 11, 13, 10, tzinfo=ZoneInfo("Europe/Belgrade"))


def listing(title, venue, price):
    return f"""<section><h2>Upcoming</h2><article data-event="yes">
      <h3><a href="/whats-on/test-exhibition-2026-11-13">{title}</a></h3>
      <div class="_when_test">13 NOV 2026</div>
      <div class="_where_test">{venue}</div>
      <div class="_price_test">{price}</div>
      <div class="_desc_test">A public cultural event with ticket details and a venue.</div>
    </article></section>"""


class AccurateAfishaPrices(unittest.TestCase):
    def test_museum_exhibition_distinguishes_adult_and_discount(self):
        title = "PREKRETNICE KA MODERNOSTI: Umetnost društva 1900-1945"
        events = parse_belgrade_cards(listing(title, "Muzej savremene umetnosti", "300 RSD"), NOW)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].price, "обычный — 600 дин., льготный — 300 дин.")
        card = format_event(events[0], "Искусство 1900–1945", "На выставке показывают работы художников.")
        self.assertIn("обычный — 600 дин., льготный — 300 дин.", card)

    def test_aggregator_price_is_not_claimed_as_full_admission(self):
        events = parse_belgrade_cards(listing("A concert", "Concert Hall", "1200 RSD"), NOW)
        self.assertEqual(events[0].price, "от 1200 дин. (по данным афиши)")

    def test_plain_text_never_asks_telegram_for_source_preview(self):
        success = Mock(ok=True, status_code=200)
        success.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = success
        self.assertTrue(publish(session, "private-test", "@afisha", "Event",
                                "https://www.runbgd.com/whats-on/test-event"))
        self.assertEqual(session.post.call_count, 1)
        self.assertTrue(session.post.call_args.kwargs["json"]["link_preview_options"]["is_disabled"])


if __name__ == "__main__":
    unittest.main()
