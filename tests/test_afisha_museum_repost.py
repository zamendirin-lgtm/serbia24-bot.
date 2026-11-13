"""Contract tests for the one-time corrected museum Afisha post (offline)."""
import unittest

from scripts.afisha_repost_museum_once import (
    CAPTION, REPOST_KEY, check_photo, SOURCE, TICKETS, PHOTO_SOURCE
)


class MuseumRepostTests(unittest.TestCase):
    def test_correction_is_short_source_linked_and_accurate(self):
        self.assertIn("600 дин., льготный — 300 дин.", CAPTION)
        self.assertIn("1 марта 2027", CAPTION)
        self.assertNotIn("открылась сегодня", CAPTION)
        self.assertIn(SOURCE, CAPTION)
        self.assertIn(TICKETS, CAPTION)
        self.assertIn(PHOTO_SOURCE, CAPTION)
        self.assertIn("CC BY 4.0", CAPTION)
        self.assertLessEqual(len(CAPTION), 1024)
        self.assertEqual(len(REPOST_KEY), 64)

    def test_photo_magic_bytes_required(self):
        self.assertTrue(check_photo(b"\\xff\\xd8\\xff" + b"a" * 12000))
        self.assertFalse(check_photo(b"<html>" + b"a" * 12000))
        self.assertFalse(check_photo(b"\\xff\\xd8\\xfftiny"))


if __name__ == "__main__":
    unittest.main()
