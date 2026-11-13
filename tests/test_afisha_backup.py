"""Checks backup event slots, local quiet period and spacing safeguards."""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from afisha_bot import post_spacing_ok
from scripts.afisha_backup import due

TZ = ZoneInfo("Europe/Belgrade")
NOW = datetime(2026, 11, 13, 12, 15, tzinfo=TZ)


class AfishaBackupTests(unittest.TestCase):
    def test_due_only_during_selected_daytime_half_hours(self):
        for hour in (8, 10, 12, 15, 18, 20):
            self.assertTrue(due(NOW.replace(hour=hour, minute=7)))
            self.assertTrue(due(NOW.replace(hour=hour, minute=22)))
            self.assertFalse(due(NOW.replace(hour=hour, minute=37)))
        for hour in (0, 6, 7, 9, 11, 14, 21, 22, 23):
            self.assertFalse(due(NOW.replace(hour=hour, minute=7)))

    def test_recent_published_event_blocks_rapid_reposting(self):
        prev = {"p1": {"published_at": (NOW - timedelta(minutes=25)).isoformat()}}
        self.assertFalse(post_spacing_ok(prev, NOW))
        older = {"p1": {"published_at": (NOW - timedelta(minutes=91)).isoformat()}}
        self.assertTrue(post_spacing_ok(older, NOW))

    def test_corrected_replacement_does_not_block_future_events(self):
        correction = {
            "correction": {
                "published_at": (NOW - timedelta(minutes=10)).isoformat(),
                "corrected_test": True,
            }
        }
        self.assertTrue(post_spacing_ok(correction, NOW))


if __name__ == "__main__":
    unittest.main()
