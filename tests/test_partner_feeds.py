"""Live network is never used in tests for authorized partner feeds."""
from __future__ import annotations
import json
import unittest
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from partner_feeds import configured_feed_urls, fetch_partner_entries
from property_bot import parse_authorized_entries

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=ZoneInfo("Europe/Belgrade"))

VALID = {
    "approved": True,
    "permission_to_publish": True,
    "url": "https://agency.example.org/listings/123",
    "city": "Панчево",
    "kind": "izdavanje-stanova",
    "title": "Недорогая квартира",
    "price_eur": 260,
    "area_m2": 41,
    "updated": "2026-11-13",
    "advertiser": "Агентство",
    "description_ru": "Меблирована.",
    "photo_permission": True,
    "photo_urls": ["https://agency.example.org/123/1.jpg",
                   "https://agency.example.org/123/2.jpg"],
}

class AuthorizedPartnerFeedTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(configured_feed_urls(), [])

    def test_requires_separate_license_confirmation(self):
        with patch.dict("os.environ", {
            "PROPERTY_PARTNER_FEEDS_ENABLED": "1",
            "PROPERTY_PARTNER_FEEDS": "https://agency.example.org/public.json",
        }, clear=True):
            self.assertEqual(configured_feed_urls(), [])

    def test_filters_insecure_urls_and_limits_feeds(self):
        with patch.dict("os.environ", {
            "PROPERTY_PARTNER_FEEDS_ENABLED": "1",
            "PROPERTY_PARTNER_LICENSE_CONFIRMED": "1",
            "PROPERTY_PARTNER_FEEDS": (
                "http://insecure.example/feed,"
                "https://localhost/internal,"
                "https://agency.example.org/feed.json,"
                "https://agency.example.org/feed.json"
            ),
        }, clear=True):
            self.assertEqual(configured_feed_urls(), ["https://agency.example.org/feed.json"])

    def test_requires_publisher_approval(self):
        draft = {**VALID, "approved": False}
        no_perms = {**VALID, "permission_to_publish": False}
        result = parse_authorized_entries([draft, no_perms, VALID], NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].price_eur, 260)
        self.assertEqual(len(result[0].photo_urls), 2)
        self.assertTrue(result[0].photos_allowed)

    def test_rejects_old_out_of_range_or_fake_schema(self):
        bad = [
            {**VALID, "updated": "2026-09-13"},
            {**VALID, "kind": "commercial"},
            {**VALID, "photo_permission": False, "price_eur": 0},
            {"approved": True, "permission_to_publish": True},
        ]
        self.assertEqual(parse_authorized_entries(bad, NOW), [])

    def test_fetch_contract_without_network(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.iter_content.return_value = [json.dumps({"listings": [VALID]}).encode("utf8")]
        fake_session = MagicMock()
        fake_session.get.return_value.__enter__.return_value = response
        with patch.dict("os.environ", {
            "PROPERTY_PARTNER_FEEDS_ENABLED": "1",
            "PROPERTY_PARTNER_LICENSE_CONFIRMED": "1",
            "PROPERTY_PARTNER_FEEDS": "https://agency.example.org/feed.json",
        }, clear=True):
            entries = fetch_partner_entries(fake_session)
        self.assertEqual(entries, [VALID])
        self.assertFalse(fake_session.get.call_args.kwargs["allow_redirects"])

    def test_refuses_non_json(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        fake_session = MagicMock()
        fake_session.get.return_value.__enter__.return_value = response
        with patch.dict("os.environ", {
            "PROPERTY_PARTNER_FEEDS_ENABLED": "1",
            "PROPERTY_PARTNER_LICENSE_CONFIRMED": "1",
            "PROPERTY_PARTNER_FEEDS": "https://agency.example.org/feed.json",
        }, clear=True):
            self.assertEqual(fetch_partner_entries(fake_session), [])

if __name__ == "__main__":
    unittest.main()
