"""Quiet hours are mandatory for all future Afisha publications."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import afisha_bot

TZ = ZoneInfo("Europe/Belgrade")


def at(hour, day=13, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


class AfishaQuietHoursTests(unittest.TestCase):
    def test_quiet_hours_and_open_hours(self):
        for now in (at(22), at(23), at(0), at(5), at(7, minute=59)):
            self.assertFalse(afisha_bot.publication_allowed(now))
        for now in (at(8), at(12), at(21, minute=59)):
            self.assertTrue(afisha_bot.publication_allowed(now))

    def test_legacy_bypass_is_ignored(self):
        with patch.dict("os.environ", {"AFISHA_ALLOW_NIGHT": "1"}, clear=True):
            self.assertFalse(afisha_bot.publication_allowed(at(23)))

    def test_one_time_exception_only_for_first_test_this_morning(self):
        self.assertTrue(afisha_bot.publication_allowed(at(5), initial=True, seen={}))
        self.assertFalse(afisha_bot.publication_allowed(at(5), initial=True, seen={"already": {}}))
        self.assertFalse(afisha_bot.publication_allowed(at(23), initial=True, seen={}))
        self.assertFalse(afisha_bot.publication_allowed(at(5, day=14), initial=True, seen={}))

    def test_run_during_night_does_not_use_network(self):
        with patch.dict("os.environ", {"AFISHA_BOT_TOKEN": "test", "AFISHA_CHAT_ID": "@test"}, clear=True):
            with patch("afisha_bot.datetime") as mocked_time:
                mocked_time.now.return_value = at(23)
                with patch("afisha_bot.load_seen", return_value={}):
                    with patch("afisha_bot.collect_official_events") as network:
                        self.assertEqual(afisha_bot.main(), 0)
                        network.assert_not_called()

    def test_one_time_run_does_not_repeat_post(self):
        with patch.dict("os.environ", {"AFISHA_FIRST_POST_ONCE": "1"}, clear=True):
            with patch("afisha_bot.load_seen", return_value={"already": {"published_at": at(5).isoformat()}}):
                with patch("afisha_bot.collect_official_events") as network:
                    self.assertEqual(afisha_bot.main(), 0)
                    network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
