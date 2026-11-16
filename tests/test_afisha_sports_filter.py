"""Sports fixture filtering must not turn the cultural Afisha into a sports feed."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from afisha_bot import Event, is_routine_sports_fixture, select

NOW = datetime(2026, 11, 16, 14, tzinfo=ZoneInfo("Europe/Belgrade"))


def evt(title, category="", description="", venue="Beogradska arena", day=19):
    return Event(
        url="https://www.runbgd.com/whats-on/" + title.lower().replace(" ", "-"),
        title=title, city="Белград", venue=venue,
        start=datetime(2026, 11, day, tzinfo=NOW.tzinfo),
        category=category,
        description=description,
        price="не указана",
    )


class AfishaSportsFilterTests(unittest.TestCase):
    def test_real_euroleague_match_examples_are_blocked(self):
        cases = (
            evt("Partizan vs Valencia (EuroLeague)", "Sport", "Basketball game in Belgrade"),
            evt("Maccabi Tel Aviv vs Dubai (EuroLeague)", "Sport", "EuroLeague basketball match"),
            evt("Crvena Zvezda vs Cedevita Olimpija (ABA liga)", "Sport"),
            evt("Партизан — Валенсия", "Basketball", "Состоится матч Евролиги"),
            evt("Crvena Zvezda - Partizan", "Sports", "Football derby match"),
            evt("Serbia protiv Spain", "Sport", "Fudbal utakmica"),
        )
        for e in cases:
            with self.subTest(title=e.title):
                self.assertTrue(is_routine_sports_fixture(e))
                self.assertEqual(select([e], {}, NOW), [])

    def test_cultural_events_in_sports_halls_are_not_blocked(self):
        cases = (
            evt("Concert of symphonic rock", "Music", "Orchestra concert in Beogradska arena"),
            evt("Tribute Maraton Serbia", "Live Music", "Tribute bands and live music"),
            evt("International Sports Fair", "Fair", "Exhibitors present sports equipment and training"),
            evt("Exhibition of basketball history", "Exhibition", "Historic basketball memorabilia"),
            evt("Family sports festival", "Festival", "Workshops, demonstrations, concerts"),
            evt("Jazz versus classical music", "Concert", "Music fusion performance"),
        )
        for e in cases:
            with self.subTest(title=e.title):
                self.assertFalse(is_routine_sports_fixture(e))

    def test_sporting_match_not_reintroduced_by_good_score(self):
        e = evt("Maccabi Tel Aviv vs Dubai (EuroLeague)", "Basketball",
                "A major international match with professional players and many fans. "
                "The contest has a detailed sports program and takes place in central Belgrade.")
        self.assertEqual(select([e], {}, NOW), [])


if __name__ == "__main__":
    unittest.main()
