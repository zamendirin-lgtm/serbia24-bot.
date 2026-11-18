"""Every Serbia24 Afisha announcement ends with the one channel hashtag."""
import unittest
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from afisha_bot import (
    AFISHA_FOOTER_HASHTAG, Event, finalize_afisha_post,
    format_event, publish,
)

NOW = datetime(2026, 11, 22, 20, 0, tzinfo=ZoneInfo("Europe/Belgrade"))
SOURCE = "https://savacentar.rs/dogadjaji/stage-show/"
POSTER = "https://savacentar.rs/wp-content/uploads/2026/11/stage-show.jpg"


def event(image=""):
    return Event(
        SOURCE,
        "Stage show",
        "Белград",
        "Сава Центар, Синий зал",
        NOW,
        category="Theatre",
        description="Культурная программа в большом зале.",
        price="от 1500 дин.",
        ticket_url="https://tickets.rs/event/stage_show_123",
        image=image,
    )


def success():
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"ok": True}
    return response


class Serbia24AfishaHashtagTests(unittest.TestCase):
    def assert_last_hashtag(self, caption):
        self.assertTrue(caption.rstrip().endswith("\n\n#Сербия24"), caption)
        self.assertEqual(caption.count("#Сербия24"), 1)
        self.assertEqual(caption.splitlines()[-1], "#Сербия24")

    def test_text_afisha_ends_after_event_links(self):
        text = format_event(event(), "Театральная постановка", "Вечерний спектакль.")
        self.assertIn(">Подробности</a>", text)
        self.assertIn(">Купить билеты</a>", text)
        self.assert_last_hashtag(text)

    def test_official_poster_icon_is_before_final_hashtag(self):
        text = format_event(event(POSTER), "Театральная постановка", "Вечерний спектакль.")
        self.assertIn(">📷</a>", text)
        self.assertLess(text.index(">📷</a>"), text.rindex("#Сербия24"))
        self.assert_last_hashtag(text)

    def test_monthly_reminder_also_has_footer(self):
        text = format_event(event(), "Театральная постановка", "Вечерний спектакль.", reminder=True)
        self.assertIn("Напоминаем", text)
        self.assert_last_hashtag(text)

    def test_camera_only_commons_credit_precedes_hashtag(self):
        initial = format_event(event(), "Театр", "Постановка.")
        linked_camera = '<a href="https://commons.wikimedia.org/wiki/File:Stage.jpg">📷</a>'
        final = finalize_afisha_post(initial, linked_camera)
        self.assertIn(linked_camera, final)
        self.assertLess(final.index(linked_camera), final.index("#Сербия24"))
        self.assert_last_hashtag(final)

    def test_finalizer_does_not_duplicate_old_hashtag(self):
        input_post = "Описание\n\n#Сербия24\n\n#Сербия24"
        self.assertEqual(finalize_afisha_post(input_post), "Описание\n\n#Сербия24")

    def test_text_telegram_send_enforces_footer(self):
        session = Mock()
        session.post.return_value = success()
        self.assertTrue(publish(session, "fake-token", "@Serbia24Afisha",
                                "Описание без хештега", SOURCE))
        args = session.post.call_args
        self.assertTrue(args.args[0].endswith("/sendMessage"))
        self.assert_last_hashtag(args.kwargs["json"]["text"])
        self.assertTrue(args.kwargs["json"]["link_preview_options"]["is_disabled"])

    def test_photo_telegram_send_enforces_footer(self):
        session = Mock()
        session.post.return_value = success()
        self.assertTrue(publish(session, "fake-token", "@Serbia24Afisha",
                                "Афиша с изображением", SOURCE, POSTER))
        args = session.post.call_args
        self.assertTrue(args.args[0].endswith("/sendPhoto"))
        self.assert_last_hashtag(args.kwargs["json"]["caption"])


if __name__ == "__main__":
    unittest.main()
