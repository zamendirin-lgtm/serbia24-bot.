"""Check Friday weekend roundups never count as three extra Telegram posts."""
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from afisha_bot import Event, posted_today, eligible_for_post, post_spacing_ok
from afisha_weekend import weekend_candidates, format_weekend, create_weekend_history

TZ = ZoneInfo("Europe/Belgrade")
FRIDAY = datetime(2026, 11, 27, 12, 20, tzinfo=TZ)


class FridayDigestTests(unittest.TestCase):
    def sample(self):
        result = []
        for i, (title, cat, day) in enumerate([
            ("Magični show za decu", "Family", 28),
            ("Jazz koncert", "Concert", 28),
            ("Izložba slika", "Exhibition", 29),
        ]):
            event = Event(
                url=f"https://novisad.travel/en/kalendar-dogadjaja/roundup-{i}",
                title=title, city="Белград" if i < 2 else "Нови-Сад",
                venue=f"Dvorana {i}",
                start=datetime(2026, 11, day, 19, tzinfo=TZ),
                category=cat, price="от 600 дин.",
                description="A beautiful cultural event in Serbia on the weekend.",
            )
            result.append(event)
        return result

    def test_three_distinct_genres_required(self):
        picks = weekend_candidates(self.sample(), {}, FRIDAY)
        self.assertEqual(len(picks), 3)
        self.assertEqual(weekend_candidates(self.sample()[:2], {}, FRIDAY), [])
        self.assertEqual(weekend_candidates(
            self.sample(), {}, datetime(2026, 11, 26, 12, tzinfo=TZ)), [])

    def test_one_message_in_daily_count_but_events_are_deduplicated(self):
        events = self.sample()
        edited = SimpleNamespace(title_ru="Интересное мероприятие", provider="test")
        bundle = [(e, edited) for e in events]
        text = format_weekend(bundle)
        self.assertIn("Куда сходить в выходные", text)
        self.assertEqual(text.count("Подробнее"), 3)
        self.assertLessEqual(len(text), 1024)
        seen = {}
        create_weekend_history(seen, bundle, FRIDAY)
        self.assertEqual(len(posted_today(seen, FRIDAY)), 1)
        self.assertFalse(post_spacing_ok(seen, FRIDAY.replace(minute=45)))
        for event in events:
            self.assertFalse(eligible_for_post(event, seen, FRIDAY))


if __name__ == "__main__":
    unittest.main()
