"""Offline tests for official MTS discovery and all-ages Afisha improvements."""
import io
import unittest
from datetime import datetime
from unittest.mock import Mock

from PIL import Image
from zoneinfo import ZoneInfo

from afisha_bot import Event, format_event, publish
from afisha_cards import branded_poster
from afisha_context import age_label, language_label, contextual_lines
from mts_events import list_event_urls, parse_detail, safe_detail_url

TZ = ZoneInfo("Europe/Belgrade")
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=TZ)
URL = "https://mtsdvorana.rs/dogadjaj/igorov-magicni-show"
TICKET = (
    "https://mtsdvorana.rs/dogadjaji/predstave/"
    "igorov-magicni-show/mts-dvorana/sala-6/2026-12-05-1200/76231"
)
INDEX = '''
<div><a href="/dogadjaj/igorov-magicni-show">IGOROV MAGIČNI SHOW</a>
<a href="/dogadjaj/isak-sabanovic">ISAK ŠABANOVIĆ</a>
<a href="/dogadjaj/igorov-magicni-show">Duplicate</a>
<a href="https://attacker.example/dogadjaj/inject">Bad</a></div>
'''
DETAIL = f'''
<html><body>
<h1>IGOROV MAGIČNI SHOW</h1>
<section><p>mts Dvorana Predstave Sala 6</p>
<p>5 dec sub mts Dvorana Predstave Sala 6 12:00 od 600
<a href="{TICKET}">Kupi ulaznicu</a></p></section>
<h2>O događaju</h2>
<p>Šou koji oduševljava sve generacije. Iluzionista izvodi
zadivljujuće trikove i publika može aktivno da učestvuje u scenskom programu.</p>
<p>Organizator: Dvorana Doma Sindikata</p>
</body></html>'''


class ImprovementsTests(unittest.TestCase):
    def test_official_mts_index_and_safe_urls(self):
        self.assertEqual(list_event_urls(INDEX), [
            URL, "https://mtsdvorana.rs/dogadjaj/isak-sabanovic",
        ])
        self.assertEqual(safe_detail_url("https://evil.test/dogadjaj/x"), "")
        self.assertEqual(safe_detail_url("http://mtsdvorana.rs/dogadjaj/x"), "")

    def test_mts_show_has_verified_date_time_and_ticket_link(self):
        event = parse_detail(DETAIL, URL, NOW)
        self.assertIsNotNone(event)
        self.assertEqual(event.start.isoformat(), "2026-12-05T12:00:00+01:00")
        self.assertEqual(event.venue, "MTS Dvorana, Sala 6")
        self.assertEqual(event.price, "от 600 дин.")
        self.assertEqual(event.city, "Белград")
        self.assertEqual(event.ticket_url, TICKET)

    def test_no_date_or_wrong_ticket_date_means_no_event(self):
        missing = DETAIL.replace("5 dec sub", "coming soon").replace(TICKET, "/buy")
        self.assertIsNone(parse_detail(missing, URL, NOW))
        inconsistent = DETAIL.replace("2026-12-05-1200", "2026-12-06-1200")
        self.assertIsNone(parse_detail(inconsistent, URL, NOW))

    def test_age_and_spoken_language_not_inferred(self):
        self.assertEqual(age_label("Deca uzrasta od 3 do 12 godina"), "3–12 лет (по информации организатора)")
        self.assertEqual(language_label("Predstava na srpskom jeziku"), "сербский")
        self.assertEqual(language_label("Sinhronizovano na srpski jezik"), "сербский")
        self.assertEqual(age_label("Porodična predstava za decu"), "")
        self.assertEqual(language_label("Izvodi se u Beogradu, Srbija"), "")

    def test_post_includes_factual_optional_age_language(self):
        event = Event(
            URL, "Dečija predstava", "Белград", "MTS Dvorana",
            datetime(2026, 12, 5, 12, tzinfo=TZ),
            description="Za decu uzrasta od 3 do 12 godina. Predstava na srpskom jeziku.",
        )
        text = format_event(event, "Детский спектакль", "В программе есть сценические иллюзии.")
        self.assertIn("<b>Возраст:</b> 3–12 лет", text)
        self.assertIn("<b>Язык:</b> сербский", text)
        self.assertIn("#Сербия24", text)

    def test_brand_card_is_original_generated_jpeg(self):
        payload = branded_poster("Семейное волшебное шоу", "Белград", "05.12.2026")
        self.assertTrue(payload.startswith(b"\xff\xd8\xff"))
        with Image.open(io.BytesIO(payload)) as im:
            self.assertEqual(im.size, (1200, 675))

    def test_publish_sends_generated_image_without_unrelated_photo(self):
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.post.return_value = response
        poster = branded_poster("Театр", "Белград", "05.12.2026")
        self.assertTrue(publish(
            session, "private-test", "@afisha", "Культурное мероприятие",
            URL, generated_card=poster,
        ))
        self.assertTrue(session.post.call_args.args[0].endswith("/sendPhoto"))
        self.assertEqual(session.post.call_args.kwargs["files"]["photo"][1], poster)


if __name__ == "__main__":
    unittest.main()
