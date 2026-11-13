"""Regression: public event dates and prices supersede stale machine metadata."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from afisha_bot import parse_jsonld_events
from afisha_editor import EditRejected, _validate

URL = "https://novisad.travel/en/kalendar-dogadjaja/example-festival"
SOURCE = """
<html>
<head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
 "name":"International Accordion Festival Eufonija",
 "url":"https://novisad.travel/en/kalendar-dogadjaja/example-festival",
 "startDate":"2026-11-25T10:00:00+01:00",
 "endDate":"2026-11-26T20:00:00+01:00",
 "description":"A festival for accordion artists with concerts and educational sessions.",
 "location":{"@type":"Place","name":"SKCNS Fabrika",
 "address":{"addressLocality":"Novi Sad"}}}
</script></head>
<body>
<div class="tribe-events-single">
<h1>International Accordion Festival Eufonija</h1>
<p>Ticket Price: Free admission.</p>
<div>Start: November 26 (2026-11-26)</div>
<div>End: November 27 (2026-11-27)</div>
</div>
</body></html>
"""

class DateIntegrityTests(unittest.TestCase):
    def test_public_dates_override_discordant_jsonld(self):
        items = parse_jsonld_events(SOURCE, URL)
        self.assertEqual(len(items), 1)
        event = items[0]
        self.assertEqual(event.start.date().isoformat(), "2026-11-26")
        self.assertEqual(event.end.date().isoformat(), "2026-11-27")
        self.assertEqual(event.price, "Бесплатно (по данным источника)")

    def test_ai_cannot_claim_upcoming_event_already_happening(self):
        event = parse_jsonld_events(SOURCE, URL)[0]
        with self.assertRaises(EditRejected):
            _validate({
                "publish": True, "interest_score": 85,
                "title_ru": "Международный фестиваль аккордеона",
                "summary_ru": "В Нови-Саде проходит фестиваль аккордеона с концертами "
                              "и образовательной программой для молодых музыкантов.",
            }, event, "test")

    def test_future_wording_is_accepted(self):
        event = parse_jsonld_events(SOURCE, URL)[0]
        edited = _validate({
            "publish": True, "interest_score": 82,
            "title_ru": "Международный фестиваль аккордеона",
            "summary_ru": "В Нови-Саде состоится фестиваль аккордеона с концертами "
                          "и образовательной программой для молодых музыкантов.",
        }, event, "test")
        self.assertEqual(edited.interest_score, 82)


if __name__ == "__main__":
    unittest.main()
