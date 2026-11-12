"""No network calls: protect facts, permissions, and Telegram post formatting."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from estate_cards import details_from_html, format_card, safe_https_url, send_photos
from property_bot import Offer, load_submitted_offers

NOW = datetime(2026, 11, 13, 14, tzinfo=ZoneInfo("Europe/Belgrade"))
URL = "https://www.4zida.rs/izdavanje-stanova/visnjica-beograd/a/0123456789abcdef01234567"


class PropertyCardTests(unittest.TestCase):
    def test_extracts_explicit_features_and_gallery(self):
        markup = """
        <html><head><meta name="description"
          content="Renoviran stan sa terasom. Ima lift. Obavezan depozit."></head>
        <body><main>
          <img src="https://images.example.com/estate1.jpg">
          <img src="https://images.example.com/estate2.jpg">
          <img src="https://images.example.com/estate1.jpg">
          <img src="http://localhost/secrets.jpg">
        </main></body></html>
        """
        location, desc, positives, negatives, photos = details_from_html(markup, URL)
        self.assertEqual(len(photos), 2)
        self.assertIn("Указан ремонт", positives)
        self.assertIn("Указан лифт", positives)
        self.assertIn("Указан терраса" if False else "Указана терраса", positives)
        self.assertEqual(negatives, ("Указан обязательный депозит",))

    def test_does_not_invent_pros_or_cons(self):
        offer = Offer(
            url=URL, city="Белград", kind="izdavanje-stanova", title="Stan",
            price_eur=420, area_m2=52, updated="2026-11-13",
            location="Нови-Београд", description_ru="Двухкомнатная квартира.",
        )
        text = format_card(offer, NOW)
        self.assertIn("Расположение:", text)
        self.assertIn("Нови-Београд", text)
        self.assertIn("Описание:", text)
        self.assertIn("Двухкомнатная квартира.", text)
        self.assertIn("Плюсы:", text)
        self.assertIn("Минусы и вопросы:", text)
        self.assertIn("Точные преимущества пока не подтверждены", text)
        self.assertIn("Недостатки не указаны", text)
        self.assertIn("420 €", text)
        self.assertIn(URL, text)

    def test_escapes_untrusted_user_description(self):
        offer = Offer(
            url=URL, city="Белград", kind="prodaja-stanova",
            title="<script>", price_eur=80000, area_m2=60,
            updated="2026-11-13", description_ru="<b>не HTML</b>",
            pros=("<iframe>",), cons=("<spam>",),
        )
        text = format_card(offer, NOW)
        self.assertNotIn("<iframe>", text)
        self.assertNotIn("<spam>", text)
        self.assertIn("&lt;iframe&gt;", text)
        self.assertIn("&lt;b&gt;", text)

    def test_url_safety(self):
        self.assertTrue(safe_https_url("https://images.example.com/a.jpg"))
        for url in ["http://example.com/a.jpg", "https://localhost/test.jpg",
                    "https://127.0.0.1/a.jpg", "https://user:pass@host.com/a.jpg",
                    "file:///tmp/a.jpg"]:
            self.assertFalse(safe_https_url(url))

    def test_album_uses_telegram_media_group(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True, "result": [{"message_id": 21}]}
        session = Mock()
        session.post.return_value = response
        result = send_photos(session, "private-token", "@test", 120, (
            "https://example.com/1.jpg", "https://example.com/2.jpg",
            "https://example.com/3.jpg",
        ))
        self.assertTrue(result)
        kwargs = session.post.call_args.kwargs
        self.assertEqual(len(kwargs["json"]["media"]), 3)
        self.assertEqual(kwargs["json"]["reply_parameters"]["message_id"], 120)

    def test_single_photo_uses_send_photo(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        session = Mock()
        session.post.return_value = response
        self.assertTrue(send_photos(session, "token", "@test", 2, ("https://example.com/1.jpg",)))
        self.assertIn("/sendPhoto", session.post.call_args.args[0])


class PermissionedIntakeTests(unittest.TestCase):
    def test_only_explicitly_approved_listings_loaded(self):
        entry = {
            "url": URL, "city": "Белград", "kind": "izdavanje-stanova",
            "title": "Аренда", "price_eur": 400, "area_m2": 50,
            "updated": "2026-11-13", "photo_permission": True,
            "description_ru": "Из объявления.", "photo_urls": [
                "https://photos.example.com/1.jpg", "http://localhost/secret"
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                Path("data").mkdir()
                path = Path("data/estate_submissions.json")
                path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf8")
                self.assertEqual(load_submitted_offers(NOW), [])
                entry.update({"approved": True, "permission_to_publish": True})
                path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf8")
                records = load_submitted_offers(NOW)
                self.assertEqual(len(records), 1)
                self.assertTrue(records[0].photos_allowed)
                self.assertEqual(records[0].photo_urls, ("https://photos.example.com/1.jpg",))
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
