"""Offline QA for 2–3 good Afisha posts/day and mandatory AI editing."""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import afisha_bot
from afisha_bot import (
    Event, MAX_DAILY_POSTS, MIN_INTEREST_SCORE, event_topic,
    interest_score, posted_today, select,
)
from afisha_editor import EditRejected, _validate, edit_event

NOW = datetime(2026, 11, 13, 12, tzinfo=ZoneInfo("Europe/Belgrade"))


def event(name="International jazz concert", description=None,
          price="от 300 дин.", venue="Kulturni centar", day=1, url_id=1):
    desc = description or (
        "International musicians will perform jazz and contemporary music "
        "in the main concert hall. Multiple performers are announced."
    )
    return Event(
        url=f"https://novisad.travel/en/kalendar-dogadjaja/event-{url_id}",
        title=name, city="Нови-Сад", venue=venue,
        start=NOW + timedelta(days=day), description=desc, price=price,
    )


class AfishaDailyQualityTests(unittest.TestCase):
    def test_quality_event_beats_weak_announcement(self):
        strong = event(url_id=1)
        weak = event("Generic event", description="Event.", price="Стоимость уточняется",
                     venue="", day=18, url_id=2)
        self.assertGreater(interest_score(strong, NOW), interest_score(weak, NOW))
        self.assertGreaterEqual(interest_score(strong, NOW), MIN_INTEREST_SCORE)
        self.assertEqual(select([weak, strong], {}, NOW), [strong])
        self.assertEqual(event_topic(strong), "concert")

    def test_maximum_three_per_local_day(self):
        new = event()
        seen = {
            f"p{i}": {
                "published_at": NOW.replace(hour=8 + i).isoformat(),
                "topic": "concert",
            } for i in range(3)
        }
        self.assertEqual(MAX_DAILY_POSTS, 3)
        self.assertEqual(len(posted_today(seen, NOW)), 3)
        self.assertEqual(select([new], seen, NOW), [])
        # The previous calendar day must not block a new day.
        for item in seen.values():
            item["published_at"] = (NOW - timedelta(days=1)).isoformat()
        self.assertEqual(select([new], seen, NOW), [new])

    def test_selection_is_ranked_not_earliest_first(self):
        weak = event("Exhibition", "An exhibition with art.", price="Стоимость уточняется",
                     venue="", day=1, url_id=3)
        strong = event(day=4, url_id=4)
        self.assertEqual(select([weak, strong], {}, NOW), [strong])

    def test_AI_rejects_unsupported_numbers(self):
        source = event()
        with self.assertRaises(EditRejected):
            _validate({
                "publish": True,
                "interest_score": 85,
                "title_ru": "Международный джазовый фестиваль",
                "summary_ru": "Музыканты исполнят 25 произведений в концертном зале. "
                              "В программе заявлены разные исполнители и стили.",
            }, source, "test")

    def test_AI_accepts_clear_source_limited_russian(self):
        source = event()
        result = _validate({
            "publish": True,
            "interest_score": 85,
            "title_ru": "Международный джазовый фестиваль",
            "summary_ru": "На сцене выступят джазовые музыканты, которые исполнят "
                          "современную музыку. В программе заявлены несколько исполнителей.",
        }, source, "test")
        self.assertEqual(result.interest_score, 85)

    def test_AI_does_not_post_when_credentials_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(edit_event(event()))

    def test_editorial_rejection_does_not_override_with_fallback_model(self):
        with patch.dict(os.environ, {"GROQ_API_KEY":"stub", "GEMINI_API_KEY":"stub"}, clear=True):
            with patch("afisha_editor._groq", side_effect=EditRejected("not relevant")):
                with patch("afisha_editor._gemini") as fallback:
                    self.assertIsNone(edit_event(event()))
                    fallback.assert_not_called()

    def test_daily_limit_short_circuits_network(self):
        with patch.dict(os.environ, {"AFISHA_BOT_TOKEN":"not-a-real-token", "AFISHA_CHAT_ID":"@test"}, clear=True):
            with patch("afisha_bot.datetime") as dt:
                dt.now.return_value = NOW
                with patch("afisha_bot.load_seen", return_value={}):
                    with patch("afisha_bot.posted_today", return_value=[{}, {}, {}]):
                        with patch("afisha_bot.collect_official_events") as get_events:
                            self.assertEqual(afisha_bot.main(), 0)
                            get_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
