"""Official Sava Centar cultural shows and holiday ballets."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from sava_events import event_links, parse_detail, collect_sava_events
from afisha_bot import event_in_window, interest_score, select, event_topic

NOW = datetime(2026, 11, 16, tzinfo=ZoneInfo("Europe/Belgrade"))
SRC = "https://savacentar.rs/dogadjaji/krcko-orascic/"
HTML = """
<html><head><meta property="og:image"
 content="https://savacentar.rs/wp-content/uploads/2026/09/krcko-orascic-poster.png"></head>
<body><main>
<h1>Krcko Oraščić</h1><h2>20.12.2026. 20:00</h2>
<p>Postoje umetnička dela bez kojih je teško zamisliti prazničnu sezonu.</p>
<p>Krcko Oraščić Petra Iljiča Čajkovskog jedan je od najvoljenijih baleta
na svetu, simbol zimske čarolije i porodičnih tradicija. Balet izvode umetnici.</p>
<a href="https://tickets.rs/event/the_nutcracker_27347">Kupite</a>
</main></body></html>
"""


class SavaCentarTests(unittest.TestCase):
    def test_exact_verified_nutcracker_event(self):
        item = parse_detail(HTML, SRC, NOW)
        self.assertIsNotNone(item)
        self.assertEqual(item.start.strftime("%Y-%m-%d %H:%M"), "2026-12-20 20:00")
        self.assertEqual(item.city, "Белград")
        self.assertIn("Синий зал", item.venue)
        self.assertEqual(item.price, "от 2 500 дин.")
        self.assertIn("15:00 и 20:00", item.description)
        self.assertEqual(item.ticket_url, "https://tickets.rs/tour/the_nutcracker_2818")
        self.assertIn("krcko-orascic-poster.png", item.image)
        self.assertTrue(event_in_window(item, NOW))
        self.assertEqual(event_topic(item), "theatre")
        self.assertGreater(interest_score(item, NOW), 52)
        self.assertEqual(len(select([item], {}, NOW)), 1)

    def test_event_list_link_discovery(self):
        page = """
        <a href="/dogadjaji/krcko-orascic/">Pročitajte više</a>
        <a href="/dogadjaji/sarah-brightman/">Koncert</a>
        <a href="https://evil.example/dogadjaji/advert">Ad</a>
        <a href="/dogadjaji/krcko-orascic/">Repeat</a>
        """
        self.assertEqual(event_links(page), [
            "https://savacentar.rs/dogadjaji/krcko-orascic/",
            "https://savacentar.rs/dogadjaji/sarah-brightman/",
        ])

    def test_no_unverified_ticket_price_or_logo(self):
        concert = HTML.replace("Krcko Oraščić", "Sergej Cetković")
        concert = concert.replace("krcko-orascic-poster.png", "logo.png")
        concert = concert.replace("20.12.2026.", "28.12.2026.")
        event = parse_detail(concert, "https://savacentar.rs/dogadjaji/sergej-cetkovic/", NOW)
        self.assertIsNotNone(event)
        self.assertEqual(event.price, "не указана")
        self.assertEqual(event.image, "")


    def test_calendar_does_not_cut_off_big_december_shows(self):
        page = "".join(
            '<a href="/dogadjaji/predstava-' + str(i) + '/">Show</a>'
            for i in range(60)
        )
        links = event_links(page)
        self.assertEqual(len(links), 60)

    def test_missing_or_out_of_range_dates(self):
        self.assertIsNone(parse_detail(HTML.replace("20.12.2026.", "20.12.2025."), SRC, NOW))
        self.assertIsNone(parse_detail(HTML.replace("20.12.2026.", "invalid"), SRC, NOW))

    def test_sports_fixture_rejected_before_selection(self):
        page = HTML.replace("Krcko Oraščić", "Partizan vs Valencia")
        page = page.replace("Postoje umetnička dela", "EuroLeague basketball game")
        page = page.replace("20.12.2026.", "19.12.2026.")
        event = parse_detail(page, "https://savacentar.rs/dogadjaji/partizan-vs-valencia/", NOW)
        if event:
            self.assertEqual(select([event], {}, NOW), [])


if __name__ == "__main__":
    unittest.main()
