"""Offline guards for user-requested one-time test photo post."""
import unittest

from scripts.afisha_test_event_once import CAPTION, PHOTO, SOURCE, TEST_KEY


class TestPhotoPublication(unittest.TestCase):
    def test_no_verbose_attribution_or_foreign_preview(self):
        self.assertIn('">📷</a>', CAPTION)
        self.assertIn("Международная туристическая ярмарка", CAPTION)
        self.assertIn("бесплатный", CAPTION)
        self.assertIn("26–28 ноября 2026 года", CAPTION)
        self.assertIn(SOURCE, CAPTION)
        self.assertIn(PHOTO, CAPTION)
        self.assertNotIn("Фото площадки", CAPTION)
        self.assertNotIn("CC BY", CAPTION)
        self.assertNotIn("Test:", CAPTION)
        self.assertLessEqual(len(CAPTION), 1024)
        self.assertEqual(len(TEST_KEY), 64)


if __name__ == "__main__":
    unittest.main()
