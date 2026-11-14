"""Offline tests for responsibly sourced Afisha images."""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from afisha_photos import (
    _allowed_licence, _candidate, find_licensed_photo, named_subject
)
from afisha_bot import publish

NOW = datetime(2026, 11, 26, tzinfo=ZoneInfo("Europe/Belgrade"))


def event(title="Magla bend", category="Music", year=2026):
    return SimpleNamespace(
        title=title, category=category,
        start=datetime(year, 11, 26, tzinfo=NOW.tzinfo),
    )


def file_info(title="File:Magla bend at music festival 2024.jpg", licence="CC BY 4.0"):
    return {
        "title": title,
        "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Magla.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Magla_bend_at_music_festival_2024.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": licence},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                "Artist": {"value": "<a href='/wiki/User:Author'>Photographer Name</a>"},
            },
        }],
    }


class AfishaLicensedPhotoTests(unittest.TestCase):
    def test_licensed_band_photo_and_credit(self):
        candidate = _candidate(file_info(), ["magla"], 2026, "artist")
        self.assertIsNotNone(candidate)
        self.assertIn("Фото исполнителя", candidate.credit_html())
        self.assertIn("Photographer Name", candidate.credit_html())
        self.assertIn("CC BY 4.0", candidate.credit_html())
        self.assertIn("commons.wikimedia.org", candidate.credit_html())

    def test_previous_year_archive_is_clearly_labelled(self):
        item = _candidate(file_info("File:Magla bend festival 2025.jpg"),
                          ["magla"], 2026, "archive")
        self.assertIsNotNone(item)
        self.assertIn("Архивное фото", item.credit_html())
        unrelated_year = _candidate(file_info("File:Magla bend 2016.jpg"),
                                    ["magla"], 2026, "archive")
        self.assertIsNone(unrelated_year)

    def test_rejects_wrong_band_and_incompatible_rights(self):
        self.assertIsNone(_candidate(file_info("File:Another band 2025.jpg"),
                                     ["magla"], 2026, "artist"))
        self.assertIsNone(_candidate(file_info(licence="CC BY-NC 4.0"),
                                     ["magla"], 2026, "artist"))
        self.assertFalse(_allowed_licence("CC BY-ND 4.0",
                                          "https://creativecommons.org/licenses/by-nd/4.0/"))
        bad = file_info()
        bad["imageinfo"][0]["extmetadata"]["Artist"]["value"] = ""
        self.assertIsNone(_candidate(bad, ["magla"], 2026, "artist"))

    def test_untrusted_host_does_not_pass_validation(self):
        bad = file_info()
        bad["imageinfo"][0]["thumburl"] = "https://not-wikimedia.example/stock.jpg"
        self.assertIsNone(_candidate(bad, ["magla"], 2026, "artist"))

    def test_names_containing_generic_words(self):
        self.assertEqual(named_subject(event('«Magla bend» — koncerti')), "Magla bend")

    def test_finds_artist_by_commons_api(self):
        resp = Mock()
        resp.json.return_value = {"query": {"pages": [file_info()]}}
        session = Mock()
        session.get.return_value = resp
        picture = find_licensed_photo(session, event())
        self.assertIsNotNone(picture)
        self.assertIn("Magla", picture.file_page)
        self.assertIn("commons.wikimedia.org/w/api.php", session.get.call_args.args[0])

    def test_generic_theatre_project_does_not_impersonate_its_performers(self):
        # Several unrelated productions have the same Gospođa ministarka title.
        e = event(title="Gospodja ministarka", category="Music")
        e.description = "Koncertni projekat u kulturnom centru."
        response = Mock()
        response.json.return_value = {"query": {"pages": [
            file_info("File:Gospodja ministarka theatre production 2013.jpg")
        ]}}
        session = Mock()
        session.get.return_value = response
        self.assertIsNone(find_licensed_photo(session, e))
        # Only the archive query is attempted; not an artist photo query.
        self.assertEqual(session.get.call_count, 1)

    def test_source_event_without_licensed_photo_returns_none(self):
        session = Mock()
        resp = Mock()
        resp.json.return_value = {"query": {"pages": []}}
        session.get.return_value = resp
        self.assertIsNone(find_licensed_photo(session, event()))

    def test_telegram_uses_verified_commons_photo(self):
        sent = Mock(ok=True)
        sent.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = sent
        image = "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Example.jpg"
        self.assertTrue(publish(session, "fake", "@afisha", "Текст", "https://source.example/a",
                                image, licensed_commons=True))
        self.assertTrue(session.post.call_args.args[0].endswith("sendPhoto"))

    def test_telegram_blocks_injected_other_host(self):
        sent = Mock(ok=True)
        sent.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = sent
        self.assertTrue(publish(session, "fake", "@afisha", "Текст", "https://source.example/a",
                                "https://evil.example/photo.jpg", licensed_commons=True))
        self.assertTrue(session.post.call_args.args[0].endswith("sendMessage"))
        self.assertTrue(session.post.call_args.kwargs["json"]["link_preview_options"]["is_disabled"])


if __name__ == "__main__":
    unittest.main()
