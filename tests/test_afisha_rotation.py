"""Regression tests for the all-ages Afisha rotation and six daily slots."""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from afisha_bot import (
    Event, MAX_DAILY_POSTS, SLOT_STARTS_UTC, TOPIC_CYCLE,
    event_topic, posting_slot, posted_today, select,
    slot_already_used, target_topic,
)

TZ = ZoneInfo("Europe/Belgrade")
BASE = datetime(2026, 11, 21, 7, 17, tzinfo=timezone.utc)


class AfishaRotationTests(unittest.TestCase):
    def make_event(self, title, category, url, *, venue="Культурный центр"):
        return Event(
            url=url, title=title, city="Белград", venue=venue,
            start=datetime(2026, 11, 28, 19, 0, tzinfo=TZ),
            description="Настоящее мероприятие с понятной культурной программой, "
                        "интересное для жителей города, состоится в указанном зале.",
            category=category,
        )

    def test_six_schedule_slots_cover_winter_and_summer(self):
        self.assertEqual(MAX_DAILY_POSTS, 6)
        self.assertEqual(len(SLOT_STARTS_UTC), 6)
        for month in (1, 7):
            for i, hour in enumerate(SLOT_STARTS_UTC):
                now = datetime(2027, month, 21, hour, 17, tzinfo=timezone.utc)
                self.assertEqual(posting_slot(now), i)
                self.assertLess(now.astimezone(TZ).hour, 22)
        self.assertIsNone(posting_slot(
            datetime(2026, 11, 21, 6, 45, tzinfo=timezone.utc)))
        self.assertIsNone(posting_slot(
            datetime(2026, 11, 21, 22, 5, tzinfo=timezone.utc)))

    def test_genres_rotate_between_days(self):
        topics = [
            target_topic(datetime(2026, 11, day, hour, 17, tzinfo=timezone.utc))
            for day in (21, 22)
            for hour in SLOT_STARTS_UTC
        ]
        self.assertEqual(len(set(topics)), len(TOPIC_CYCLE))
        self.assertEqual(target_topic(BASE), "family")
        self.assertEqual(
            target_topic(datetime(2026, 11, 21, 9, 17, tzinfo=timezone.utc)),
            "concert",
        )

    def test_backup_run_never_gets_second_post_in_same_slot(self):
        seen = {
            "first": {"published_at": BASE.isoformat(), "topic": "family"},
        }
        self.assertTrue(slot_already_used(seen, BASE + timedelta(minutes=30)))
        self.assertFalse(slot_already_used(seen, BASE + timedelta(hours=2)))
        self.assertEqual(len(posted_today(seen, BASE)), 1)

    def test_coverage_includes_all_age_groups_and_interests(self):
        cases = [
            ("Magični show za decu", "family"),
            ("Stand-up komedija", "comedy"),
            ("Simfonijski orkestar", "classical"),
            ("Balet u pozorištu", "theatre"),
            ("Filmska projekcija", "cinema"),
            ("DJ set techno", "nightlife"),
            ("Festival hrane", "festival"),
            ("Sajam knjiga", "fair"),
            ("Izložba skulptura", "exhibition"),
            ("Kreativna radionica", "workshop"),
            ("Rock koncert", "concert"),
        ]
        for title, topic in cases:
            with self.subTest(title=title):
                self.assertEqual(event_topic(self.make_event(
                    title, "", "https://example.org/" + str(len(title)))), topic)

    def test_rotation_prioritises_a_good_family_event_over_another_concert(self):
        family = self.make_event("Magični show za decu", "Family",
                                 "https://example.org/show")
        concert = self.make_event("Big concert", "Concert",
                                  "https://example.org/concert",
                                  venue="Sava Centar, Plava dvorana")
        ranked = select([concert, family], {}, BASE)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].url, family.url)

    def test_six_posts_is_the_daily_cap(self):
        seen = {
            f"published-{i}": {
                "published_at": (BASE + timedelta(minutes=i)).isoformat(),
                "topic": "concert",
            }
            for i in range(6)
        }
        event = self.make_event("Rock koncert", "Concert",
                                "https://example.org/another-concert")
        self.assertEqual(select([event], seen, BASE + timedelta(hours=2)), [])


if __name__ == "__main__":
    unittest.main()
