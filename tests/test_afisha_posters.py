"""The official MTS poster is used before the decorative Serbia 24 card."""
import io
import unittest
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from PIL import Image

from afisha_media import find_official_event_poster, trusted_event_image
from afisha_bot import _official_poster, publish
from mts_events import parse_detail

TZ = ZoneInfo("Europe/Belgrade")
NOW = datetime(2026, 11, 22, 9, tzinfo=TZ)
EVENT_URL = "https://mtsdvorana.rs/dogadjaj/igorov-novogodisnji-magicni-show"
OFFICIAL_POSTER = (
    "https://kombank.s3.amazonaws.com/2026/11/"
    "32f1b6f7-fbb1-4a20-af36-d3632f5b3e2a.jpg"
)
LOGO = "https://kombank.s3.amazonaws.com/logo/logo_mts.jpg"
PAYMENT = "https://kombank.s3.amazonaws.com/2026/11/visa-card.jpg"
HTML = f"""
<html><head><meta property="og:image" content="{LOGO}"></head>
<body><header><img alt="MTS Dvorana" src="{LOGO}"></header>
<div class="event-page">
  <picture><img alt="IGOROV NOVOGODIŠNJI MAGIČNI SHOW"
                src="{OFFICIAL_POSTER}"></picture>
  <h1>IGOROV NOVOGODIŠNJI MAGIČNI SHOW</h1>
  <p>mts Dvorana Predstave Sala 6 20 dec ned mts Dvorana
     Predstave Sala 6 11:00 od 700</p>
  <a href="https://mtsdvorana.rs/dogadjaji/predstave/igorov-novogodisnji-magicni-show/mts-dvorana/sala-6/2026-12-20-1100/5221">Kupi ulaznicu</a>
  <h2>O događaju</h2>
  Šou koji oduševljava sve generacije. Izvođač prikazuje iluzije na sceni,
  a publika učestvuje u interaktivnom novogodišnjem programu.
</div>
<footer><img alt="Visa Secure" src="{PAYMENT}"></footer></body></html>
"""


class OfficialMtsImageTests(unittest.TestCase):
    def test_site_event_image_from_exact_cdn_and_event_source(self):
        soup = BeautifulSoup(HTML, "html.parser")
        self.assertEqual(find_official_event_poster(soup, EVENT_URL, "IGOROV NOVOGODIŠNJI MAGIČNI SHOW"),
                         OFFICIAL_POSTER)
        event = parse_detail(HTML, EVENT_URL, NOW)
        self.assertIsNotNone(event)
        self.assertEqual(event.image, OFFICIAL_POSTER)
        self.assertEqual(event.start.strftime("%Y-%m-%d %H:%M"), "2026-12-20 11:00")

    def test_mts_bucket_only_approved_for_exact_venue_event_source(self):
        self.assertTrue(_official_poster(OFFICIAL_POSTER, EVENT_URL))
        self.assertFalse(_official_poster(OFFICIAL_POSTER))
        self.assertFalse(_official_poster(OFFICIAL_POSTER, "https://savacentar.rs/dogadjaji/nesto"))
        self.assertFalse(trusted_event_image("https://evil.test/2026/11/a.jpg", EVENT_URL))
        self.assertFalse(trusted_event_image(LOGO, EVENT_URL))
        self.assertFalse(trusted_event_image(PAYMENT, EVENT_URL))
        self.assertFalse(trusted_event_image("http://kombank.s3.amazonaws.com/2026/11/x.jpg", EVENT_URL))
        self.assertFalse(trusted_event_image("https://kombank.s3.amazonaws.com/2026/11/x.jpg",
                                             "https://mtsdvorana.rs/not-an-event"))

    def test_lazy_loading_real_poster_and_rejection_of_site_logo(self):
        markup = (
            '<h1>IGOROV NOVOGODIŠNJI MAGIČNI SHOW</h1>'
            f'<img alt="MTS Dvorana" src="{LOGO}">'
            f'<img alt="IGOROV NOVOGODIŠNJI MAGIČNI SHOW" '
            f'data-src="{OFFICIAL_POSTER}" src="/placeholder.jpg">'
        )
        self.assertEqual(find_official_event_poster(BeautifulSoup(markup, "html.parser"),
                                                    EVENT_URL, "IGOROV NOVOGODIŠNJI MAGIČNI SHOW"),
                         OFFICIAL_POSTER)
        self.assertEqual(find_official_event_poster(BeautifulSoup(
            f'<img alt="MTS Dvorana" src="{LOGO}">', "html.parser"),
            EVENT_URL, "IGOROV NOVOGODIŠNJI MAGIČNI SHOW"), "")

    def test_real_image_takes_priority_over_prepared_branded_card(self):
        session = Mock()
        ok = Mock(ok=True)
        ok.json.return_value = {"ok": True}
        session.post.return_value = ok
        result = publish(session, "secret-test", "@afisha", "Игор покажет фокусы",
                         EVENT_URL, OFFICIAL_POSTER, generated_card=b"fallback")
        self.assertTrue(result)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.kwargs["json"]["photo"], OFFICIAL_POSTER)

    def test_failed_real_photo_uses_upload_before_fallback_card(self):
        session = Mock()
        error = Mock(ok=False, status_code=400)
        ok = Mock(ok=True)
        ok.json.return_value = {"ok": True}
        session.post.side_effect = [error, ok]
        response = Mock(content=b"\xff\xd8\xff" + b"p" * 2048)
        response.raise_for_status.return_value = None
        response.url = OFFICIAL_POSTER
        session.get.return_value = response
        self.assertTrue(publish(session, "test", "@afisha", "Шоу Игоря", EVENT_URL,
                                OFFICIAL_POSTER, generated_card=b"fallback"))
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.post.call_args.kwargs["files"]["photo"][1], response.content)

    def test_both_real_photo_attempts_fail_then_brand_card_used(self):
        session = Mock()
        fail = Mock(ok=False, status_code=400)
        ok = Mock(ok=True)
        ok.json.return_value = {"ok": True}
        session.post.side_effect = [fail, fail, ok]
        response = Mock(content=b"\xff\xd8\xff" + b"p" * 2048)
        response.raise_for_status.return_value = None
        response.url = OFFICIAL_POSTER
        session.get.return_value = response
        self.assertTrue(publish(session, "test", "@afisha", "Шоу Игоря", EVENT_URL,
                                OFFICIAL_POSTER, generated_card=b"fallback"))
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(session.post.call_args.kwargs["files"]["photo"][1], b"fallback")

    def test_webp_official_image_converts_to_jpeg_for_upload(self):
        webp_url = OFFICIAL_POSTER.replace(".jpg", ".webp")
        raw = io.BytesIO()
        Image.effect_noise((360, 420), 55).convert("RGB").save(raw, "WEBP", quality=85)
        session = Mock()
        fail = Mock(ok=False, status_code=400)
        ok = Mock(ok=True)
        ok.json.return_value = {"ok": True}
        session.post.side_effect = [fail, ok]
        response = Mock(content=raw.getvalue())
        response.raise_for_status.return_value = None
        response.url = webp_url
        session.get.return_value = response
        self.assertTrue(publish(session, "test", "@afisha", "Шоу Игоря", EVENT_URL, webp_url))
        self.assertTrue(session.post.call_args.kwargs["files"]["photo"][1].startswith(b"\xff\xd8\xff"))


if __name__ == "__main__":
    unittest.main()
