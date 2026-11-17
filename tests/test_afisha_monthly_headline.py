"""Headline events can be previewed early and reminded monthly, but not spammed."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from afisha_bot import (
    Event, TZ, is_marquee_event, event_in_window, edition_history,
    eligible_for_post, monthly_reminder_due, interest_score, select, format_event,
    load_curated_events, same_edition,
)

NOW = datetime(2026, 11, 17, 13, tzinfo=TZ)
EXIT = Event(
    url="https://www.exitfest.org/exit-2027",
    title="EXIT 2027 — возвращение фестиваля в Нови-Сад",
    city="Нови-Сад",
    venue="Петроварадинская крепость",
    start=datetime(2027, 7, 1, tzinfo=TZ),
    end=datetime(2027, 7, 4, 23, 59, tzinfo=TZ),
    category="Festival",
    description=(
        "Фестиваль EXIT возвращается в Нови-Сад. "
        "Dance Arena и No Sleep — официально заявленные сцены будущего события."
    ),
)
SMALL = Event(
    url="https://belgradelife.com/en/events/booze-glory",
    title="Booze & Glory — концерт в Белграде",
    city="Белград",
    venue="Nova Zappa Barka",
    start=datetime(2026, 11, 22, 19, tzinfo=TZ),
    category="Concert",
    description=(
        "Лондонская панк-группа выступит в Белграде 22 ноября. "
        "Начало в 19 часов, проверенная концертная программа."
    ),
    ticket_url="https://new.gigstix.com/event/booze-and-glory-beograd-22-novembar-2026/",
)


def history(event, posted_at):
    return {"url": event.url,
            "event_start": event.start.isoformat(),
            "published_at": posted_at.isoformat(),
            "title": event.title,
            "city": event.city,
            "venue": event.venue,
            "topic": "festival"}


class MonthlyHeadlineAfishaTests(unittest.TestCase):
    def test_exit_can_be_announced_months_early(self):
        self.assertTrue(is_marquee_event(EXIT))
        self.assertTrue(event_in_window(EXIT, NOW))
        self.assertGreater(interest_score(EXIT, NOW) - 16, 50)
        self.assertEqual(select([EXIT], {}, NOW), [EXIT])
        too_early = replace(EXIT, start=datetime(2028, 7, 1, tzinfo=TZ),
                            end=datetime(2028, 7, 4, tzinfo=TZ))
        self.assertFalse(event_in_window(too_early, NOW))
        self.assertEqual(select([too_early], {}, NOW), [])

    def test_normal_concert_is_one_time_only(self):
        self.assertFalse(is_marquee_event(SMALL))
        self.assertTrue(event_in_window(SMALL, NOW))
        records = {SMALL.key: history(SMALL, NOW - timedelta(days=60))}
        self.assertFalse(monthly_reminder_due(SMALL, records, NOW))
        self.assertEqual(select([SMALL], records, NOW), [])

    def test_monthly_reminder_requires_30_full_days(self):
        yesterday = NOW - timedelta(days=29)
        posted = {EXIT.key: history(EXIT, yesterday)}
        self.assertFalse(monthly_reminder_due(EXIT, posted, NOW))
        self.assertEqual(select([EXIT], posted, NOW), [])

        ago = NOW - timedelta(days=31)
        posted = {EXIT.key: history(EXIT, ago)}
        self.assertTrue(monthly_reminder_due(EXIT, posted, NOW))
        self.assertEqual(select([EXIT], posted, NOW), [EXIT])
        text = format_event(EXIT, "EXIT возвращается!", "Специальный фестиваль в Нови-Саде.",
                            reminder=True)
        self.assertIn("🔔", text)
        self.assertIn("Напоминаем", text)

        another = {**posted, "reminder": history(EXIT, NOW - timedelta(hours=1))}
        self.assertFalse(monthly_reminder_due(EXIT, another, NOW))
        self.assertEqual(select([EXIT], another, NOW), [])

    def test_no_reminders_after_start(self):
        day = datetime(2027, 7, 1, 13, tzinfo=TZ)
        posted = {EXIT.key: history(EXIT, NOW)}
        self.assertFalse(monthly_reminder_due(EXIT, posted, day))
        self.assertFalse(eligible_for_post(EXIT, posted, day))

    def test_annual_edition_is_not_a_duplicate(self):
        old_event = replace(EXIT, start=datetime(2026, 7, 1, tzinfo=TZ),
                            end=datetime(2026, 7, 4, tzinfo=TZ))
        history_row = history(old_event, NOW - timedelta(days=200))
        self.assertFalse(same_edition(EXIT, history_row))
        self.assertTrue(eligible_for_post(EXIT, {"old": history_row}, NOW))

    def test_bogus_duplicate_without_known_publication_date_fails_closed(self):
        row = history(EXIT, NOW - timedelta(days=90))
        row.pop("published_at")
        self.assertFalse(monthly_reminder_due(EXIT, {"old": row}, NOW))
        self.assertEqual(select([EXIT], {"old": row}, NOW), [])

    def test_nearby_events_have_priority_over_2027_promotions(self):
        shortlist = select([EXIT, SMALL], {}, NOW)
        self.assertEqual(shortlist[0].title, SMALL.title)
        self.assertIn(EXIT, shortlist)

    def test_major_venue_may_be_promoted_early_with_real_facts(self):
        e = Event("https://savacentar.rs/dogadjaji/family-show/",
                  "Family musical", "Белград", "Сава Центар, Синий зал",
                  NOW + timedelta(days=120),
                  category="Ballet",
                  description="Large ballet production with orchestra and a rich stage show, "
                              "performed in the main hall for the whole family.",
                  image="https://savacentar.rs/wp-content/uploads/show.jpg")
        self.assertTrue(is_marquee_event(e))
        self.assertTrue(event_in_window(e, NOW))

    def test_curated_events_have_accurate_sources_and_dates(self):
        records = json.loads(Path("data/afisha_events.json").read_text(encoding="utf8"))
        urls = {row["url"] for row in records}
        self.assertIn("https://www.exitfest.org/exit-2027", urls)
        self.assertIn("https://belgradelife.com/en/events/booze-glory", urls)
        parsed = load_curated_events(NOW)
        by_url = {e.url: e for e in parsed}
        self.assertEqual(by_url["https://www.exitfest.org/exit-2027"].end.date().isoformat(),
                         "2027-07-04")
        self.assertIn("3 700", by_url["https://belgradelife.com/en/events/booze-glory"].price)
        self.assertTrue(by_url["https://www.exitfest.org/exit-2027"].start.date().isoformat() == "2027-07-01")


if __name__ == "__main__":
    unittest.main()
