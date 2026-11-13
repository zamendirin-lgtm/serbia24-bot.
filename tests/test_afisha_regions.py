"""City source extraction is conservative and never assumes missing prices or tickets."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from belgrade_events import parse_belgrade_cards
from subotica_events import parse_subotica_cards
from afisha_bot import select

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=ZoneInfo("Europe/Belgrade"))
BELGRADE = """
<section>
  <header><h2>Upcoming</h2></header>
  <article data-event="tribute-maraton-serbia-2026-11-14">
    <h3><a href="/whats-on/tribute-maraton-serbia-2026-11-14">TRIBUTE MARATON SERBIA</a></h3>
    <p class="_when_3unba_31">14 NOV 2026</p>
    <span class="_category_3unba_79">Live Music</span>
    <span class="_price_3unba_82">1890 RSD</span>
    <p class="_where_3unba_95">Dorćol Platz</p>
    <p class="_desc_3unba_121">A music festival with several tribute bands at Dorćol Platz.</p>
    <a class="_tickets_3unba_129" href="https://tickets.rs/event/tribute_maraton_serbia__28395">Tickets →</a>
  </article>
  <article data-event="unpriced-exhibition-2026-11-20">
    <h3><a href="/whats-on/exhibition-2026-11-20">An art exhibition</a></h3>
    <p class="_when_3unba_31">20 NOV 2026</p>
    <span class="_category_3unba_79">Culture &amp; Exhibitions</span>
    <p class="_where_3unba_95">Art gallery</p>
    <p class="_desc_3unba_121">An exhibition of art from Serbia.</p>
    <a href="/whats-on/exhibition-2026-11-20">Details</a>
  </article>
</section>
<section><h2>Past</h2>
  <article data-event="old">
    <h3><a href="/whats-on/old">Old event</a></h3>
    <p class="_when_3unba_31">10 OCT 2026</p>
  </article>
</section>
"""
SUBOTICA = """
<div class="em-event em-item">
  <div class="em-item-info">
    <h3 class="em-item-title">
      <a href="https://visitsubotica.rs/events/xvi-festival-mlade-rakije/">18. Фестивал младе ракије</a>
    </h3>
    <div class="em-event-date">14.11.2026</div>
    <div class="em-event-time">10:00 - 17:00</div>
    <div class="em-event-location"><a>Љутово</a></div>
    <div class="em-event-categories"><a>Вашари и изложбе</a></div>
    <div class="em-item-desc">Гастрономски фестивал са дегустацијама домаћих производа и програмом за посетиоце.</div>
    <a href="https://visitsubotica.rs/events/xvi-festival-mlade-rakije/">Више информација</a>
  </div>
</div>
"""


class RegionTests(unittest.TestCase):
    def test_belgrade_event_and_real_ticket_link(self):
        events = parse_belgrade_cards(BELGRADE, NOW)
        self.assertEqual(len(events), 2)
        event = events[0]
        self.assertEqual(event.city, "Белград")
        self.assertEqual(event.price, "от 1890 дин. (по данным афиши)")
        self.assertEqual(event.start.date().isoformat(), "2026-11-14")
        self.assertEqual(event.venue, "Dorćol Platz")
        self.assertEqual(event.ticket_url, "https://tickets.rs/event/tribute_maraton_serbia__28395")
        self.assertEqual(events[1].price, "не указана")
        self.assertFalse(events[1].ticket_url)
        self.assertTrue(select([event], {}, NOW))

    def test_subotica_tourist_calendar_with_outlying_village(self):
        events = parse_subotica_cards(SUBOTICA, NOW)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e.city, "Суботица и окрестности")
        self.assertEqual(e.venue, "Љутово")
        self.assertEqual(e.start.strftime("%Y-%m-%d %H:%M"), "2026-11-14 10:00")
        self.assertEqual(e.price, "не указана")
        self.assertFalse(e.ticket_url)
        self.assertIn("Фестивал", e.title)
        self.assertTrue(select(events, {}, NOW))

    def test_same_multi_day_exhibition_not_published_repeatedly(self):
        from dataclasses import replace
        from afisha_bot import event_series_key
        today = parse_belgrade_cards(BELGRADE, NOW)[1]
        another_date = replace(
            today,
            url="https://www.runbgd.com/whats-on/exhibition-2026-11-21",
            start=datetime(2026, 11, 21, tzinfo=NOW.tzinfo),
        )
        self.assertEqual(event_series_key(today.url), event_series_key(another_date.url))
        self.assertEqual(len(select([today, another_date], {}, NOW)), 1)
        seen = {"already": {"url": today.url, "published_at": NOW.isoformat(), "topic": "exhibition"}}
        self.assertEqual(select([another_date], seen, NOW), [])

    def test_no_untrusted_ticket_or_bad_date(self):
        unsafe = BELGRADE.replace(
            "https://tickets.rs/event/tribute_maraton_serbia__28395",
            "javascript:alert(1)",
        )
        e = parse_belgrade_cards(unsafe, NOW)[0]
        self.assertEqual(e.ticket_url, "")
        old = BELGRADE.replace("14 NOV 2026", "14 OCT 2026")
        self.assertTrue(all(e.title != "TRIBUTE MARATON SERBIA"
                            for e in parse_belgrade_cards(old, NOW)))


if __name__ == "__main__":
    unittest.main()
