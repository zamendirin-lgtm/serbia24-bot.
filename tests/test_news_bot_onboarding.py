"""No-network tests for the public news bot onboarding flow."""
import tempfile
import unittest
from pathlib import Path

from scripts import news_bot_onboarding as inbox


def update(number, chat_type="private", text="/start", chat_id=123):
    return {
        "update_id": number,
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"is_bot": False},
            "text": text,
        },
    }


class NewsBotOnboardingTests(unittest.TestCase):
    def test_start_and_help_in_private_chat(self):
        for command in ("/start", "/start ref", "/help", "/news", "/start@Serbia24_bot"):
            self.assertTrue(inbox.should_welcome(update(1, text=command)), command)
        self.assertFalse(inbox.should_welcome(update(1, "group")))
        self.assertFalse(inbox.should_welcome(update(1, text="Привет")))
        self.assertFalse(inbox.should_welcome(update(1, text="/startfake")))
        self.assertFalse(inbox.should_welcome({
            "update_id": 1,
            "message": {
                "chat": {"id": 1, "type": "private"},
                "from": {"is_bot": True},
                "text": "/start",
            }
        }))

    def test_three_buttons_news_first_and_opt_in(self):
        buttons = [row[0] for row in inbox.subscribe_keyboard()["inline_keyboard"]]
        self.assertEqual(
            [button["url"] for button in buttons],
            [
                "https://t.me/serbia24live",
                "https://t.me/Serbia24Afisha",
                "https://t.me/baraholka_serbia",
            ],
        )
        self.assertIn("Подписаться", buttons[0]["text"])
        self.assertIn("Выберите канал", inbox.WELCOME_TEXT)
        self.assertIn("«Подписаться»", inbox.WELCOME_TEXT)
        self.assertIn("Новости", inbox.WELCOME_TEXT)
        self.assertIn("Афиша", inbox.WELCOME_TEXT)
        self.assertIn("Барахолка", inbox.WELCOME_TEXT)

    def test_start_sends_one_message_with_url_button(self):
        state = inbox.default_state()
        calls, checkpoints = [], []
        def fake_api(token, method, payload):
            calls.append((method, payload))
            return True
        replied = inbox.process_updates(
            "dummy-secret",
            [update(3, text="/start hello"), update(4, text="Спасибо")],
            state,
            api=fake_api,
            persist=lambda state: checkpoints.append(state.copy()),
        )
        self.assertEqual(replied, 1)
        self.assertEqual(state["next_offset"], 5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sendMessage")
        self.assertEqual(calls[0][1]["chat_id"], 123)
        self.assertEqual(
            calls[0][1]["reply_markup"]["inline_keyboard"][0][0]["url"],
            inbox.CHANNEL_URL,
        )
        self.assertEqual([x["next_offset"] for x in checkpoints], [4, 5])

    def test_failed_reply_does_not_acknowledge_the_update(self):
        state = inbox.default_state()
        checkpoints = []
        def failing_api(token, method, payload):
            raise inbox.TelegramAPIError("send failure")
        with self.assertRaises(inbox.TelegramAPIError):
            inbox.process_updates(
                "dummy-secret", [update(10)],
                state, api=failing_api,
                persist=lambda state: checkpoints.append(state.copy()),
            )
        self.assertEqual(state["next_offset"], 0)
        self.assertEqual(checkpoints, [])

    def test_repeat_or_non_private_updates_do_not_get_a_reply(self):
        state = {"next_offset": 10, "profile_configured": False}
        sent = []
        replied = inbox.process_updates(
            "dummy-secret",
            [update(9), update(10, "group"), update(11, text="anything")],
            state,
            api=lambda *args: sent.append(args),
            persist=lambda _: None,
        )
        self.assertEqual(replied, 0)
        self.assertEqual(sent, [])
        self.assertEqual(state["next_offset"], 12)

    def test_profile_links_to_public_channel(self):
        calls = []
        inbox.configure_profile(
            "dummy-secret", api=lambda token, method, payload: calls.append((method, payload))
        )
        self.assertEqual(
            [method for method, _ in calls],
            ["setMyShortDescription", "setMyDescription", "setMyCommands"],
        )
        self.assertIn(inbox.CHANNEL_URL, calls[1][1]["description"])
        self.assertIn(inbox.AFISHA_URL, calls[1][1]["description"])
        self.assertIn(inbox.MARKET_URL, calls[1][1]["description"])
        self.assertIn("@serbia24live", calls[0][1]["short_description"])
        self.assertIn("@Serbia24Afisha", calls[0][1]["short_description"])
        self.assertIn("@baraholka_serbia", calls[0][1]["short_description"])
        self.assertLessEqual(len(inbox.SHORT_DESCRIPTION), 120)
        self.assertLessEqual(len(inbox.DESCRIPTION), 512)

    def test_offset_storage_does_not_contain_chat_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"next_offset": 45, "profile_configured": True}
            inbox.write_state(state, path)
            self.assertEqual(inbox.read_state(path), state)
            self.assertEqual(set(inbox.read_state(path)), {"next_offset", "profile_configured"})


if __name__ == "__main__":
    unittest.main()
