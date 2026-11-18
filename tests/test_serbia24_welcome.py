"""Telegram /start must return Afisha-first opt-in links, never broadcast."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.serbia24_welcome import (
    CHANNELS, COMMAND, KEYBOARD, WELCOME_TEXT, handle_update,
    command_requested, poll_bot, read_state, write_state,
)

NOW = 1795000000


def command(text="/start", *, typ="private", age=0, uid=20, chatid=12):
    return {
        "update_id": uid,
        "message": {
            "date": NOW - age,
            "chat": {"id": chatid, "type": typ},
            "from": {"id": 99999, "is_bot": False},
            "text": text,
        },
    }


def ok(result):
    response = Mock(status_code=200)
    response.json.return_value = {"ok": True, "result": result}
    return response


class Serbia24WelcomeTests(unittest.TestCase):
    def test_afisha_first_then_news_then_baraholka(self):
        self.assertEqual([x[1] for x in CHANNELS], [
            "https://t.me/Serbia24Afisha",
            "https://t.me/serbia24live",
            "https://t.me/baraholka_serbia",
        ])
        self.assertEqual([x[0] for x in KEYBOARD["inline_keyboard"]],
                         [[{"text": title, "url": url}] for title, url, _ in CHANNELS])
        self.assertIn("🎭 Сербия 24 | Афиша", WELCOME_TEXT)
        self.assertIn("📰 Сербия 24 | Новости", WELCOME_TEXT)
        self.assertIn("🛍 Барахолка Сербии", WELCOME_TEXT)

    def test_bot_is_contacted_only_after_explicit_private_command(self):
        for text in ("/start", "/help", "/channels", "/start@Serbia24ExistingBot",
                     "/start promo2026"):
            self.assertTrue(command_requested(command(text)["message"], "Serbia24ExistingBot"))
        for text in ("Привет", "start", "дайте новости",
                     "/start@other_bot", "/unknown", ""):
            self.assertFalse(command_requested(command(text)["message"], "Serbia24ExistingBot"))
        self.assertFalse(command_requested(command(typ="supergroup")["message"], "Serbia24ExistingBot"))
        self.assertFalse(command_requested(command(typ="channel")["message"], "Serbia24ExistingBot"))

    def test_one_welcome_with_three_real_url_buttons(self):
        session = Mock()
        session.post.return_value = ok({"message_id": 100})
        result = handle_update(command(), "Serbia24ExistingBot", "secret", session, NOW)
        self.assertTrue(result)
        args = session.post.call_args.kwargs["json"]
        self.assertEqual(args["chat_id"], 12)
        self.assertEqual(args["text"], WELCOME_TEXT)
        self.assertEqual(args["reply_markup"], KEYBOARD)
        self.assertTrue(args["link_preview_options"]["is_disabled"])
        self.assertNotIn("secret", WELCOME_TEXT)

    def test_refuse_old_messages_and_noncommands(self):
        session = Mock()
        self.assertFalse(handle_update(command(age=25*3600), "Serbia24ExistingBot", "secret", session, NOW))
        self.assertFalse(handle_update(command(text="hello"), "Serbia24ExistingBot", "secret", session, NOW))
        self.assertFalse(handle_update(command(typ="group"), "Serbia24ExistingBot", "secret", session, NOW))
        session.post.assert_not_called()

    def test_saved_offset_prevents_duplicate_reply(self):
        session = Mock()
        session.post.side_effect = [
            ok({"id": 123, "username": "Serbia24ExistingBot"}),  # getMe
            ok({"url": ""}),                                   # getWebhookInfo
            ok([command(uid=10), command("/start", uid=11)]),  # getUpdates
        ] + [
            ok({"message_id": 101}),
            ok({"message_id": 102}),
        ]
        # request calls use consecutive responses: install side_effect
        # in actual API call order (sendMessage happens after getUpdates).
        state = {"123": 11}
        session.post.side_effect = [
            ok({"id": 123, "username": "Serbia24ExistingBot"}),
            ok({"url": ""}),
            ok([command(uid=10), command(uid=11)]),
            ok({"message_id": 102}),
        ]
        self.assertEqual(poll_bot(session, "secret", state, set(), now=NOW), (1, 1))
        self.assertEqual(state["123"], 12)
        self.assertEqual(session.post.call_count, 4)

    def test_reject_webhook_without_modifying_it(self):
        session = Mock()
        session.post.side_effect = [
            ok({"id": 123, "username": "Serbia24ExistingBot"}),
            ok({"url": "https://example.com/existing-bot-handler"}),
        ]
        state = {}
        self.assertEqual(poll_bot(session, "secret", state, set(), now=NOW), (0, 0))
        self.assertEqual(state, {})
        self.assertEqual(session.post.call_count, 2)

    def test_failed_reply_never_advances_offset(self):
        session = Mock()
        fail = Mock(status_code=403)
        session.post.side_effect = [
            ok({"id": 123, "username": "Serbia24ExistingBot"}),
            ok({"url": ""}),
            ok([command(uid=10)]),
            fail,
        ]
        state = {}
        with self.assertRaises(RuntimeError):
            poll_bot(session, "secret", state, set(), now=NOW)
        self.assertEqual(state, {})

    def test_state_contains_only_update_ids_not_users(self):
        with tempfile.TemporaryDirectory() as name:
            file = Path(name) / "offsets.json"
            write_state({"123": 800}, file)
            text = file.read_text()
            self.assertNotIn("99999", text)
            self.assertEqual(read_state(file), {"123": 800})
            file.write_text('{"abc": 17, "123": true, "456": 42}')
            self.assertEqual(read_state(file), {"456": 42})


if __name__ == "__main__":
    unittest.main()
