import os
import unittest
from unittest.mock import patch

from scripts.check_afisha_telegram import main


class AfishaTelegramSwitchTests(unittest.TestCase):
    @patch("scripts.check_afisha_telegram._request")
    def test_reuses_bot_on_confirmed_afisha_channel(self, req):
        req.side_effect = [
            {"id": 1001, "username": "Serbia24ExistingBot"},
            {"id": -100123, "title": "🇷🇸 Сербия 24 | Афиша и выставки", "type": "channel"},
            {"status": "administrator", "can_post_messages": True},
        ]
        with patch.dict(os.environ, {"AFISHA_BOT_TOKEN": "test-token", "AFISHA_CHAT_ID": "@oldproperty"}, clear=True):
            self.assertEqual(main(), 0)
        self.assertEqual(req.call_count, 3)

    @patch("scripts.check_afisha_telegram._request")
    def test_refuses_wrong_channel(self, req):
        req.side_effect = [
            {"id": 1001, "username": "NewsBot"},
            {"id": -100123, "title": "🇷🇸 Сербия 24 | Новости", "type": "channel"},
        ]
        with patch.dict(os.environ, {"AFISHA_BOT_TOKEN": "test-token", "AFISHA_CHAT_ID": "@news"}, clear=True):
            self.assertEqual(main(), 1)
        self.assertEqual(req.call_count, 2)

    @patch("scripts.check_afisha_telegram._request")
    def test_refuses_missing_channel_permissions(self, req):
        req.side_effect = [
            {"id": 1001, "username": "ExistingBot"},
            {"id": -100123, "title": "Сербия 24 Афиша", "type": "channel"},
            {"status": "administrator", "can_post_messages": False},
        ]
        with patch.dict(os.environ, {"AFISHA_BOT_TOKEN": "test-token", "AFISHA_CHAT_ID": "@afisha"}, clear=True):
            self.assertEqual(main(), 1)

    @patch("scripts.check_afisha_telegram._request")
    def test_skips_if_channel_username_not_set(self, req):
        with patch.dict(os.environ, {"AFISHA_BOT_TOKEN": "test-token"}, clear=True):
            self.assertEqual(main(), 1)
        req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
