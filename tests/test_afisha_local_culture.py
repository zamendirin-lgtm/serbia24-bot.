"""Small official venue events and small-culture aggregator facts (offline)."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from local_culture_events import (
    loz_links, loz_detail, afisha_cards, afisha_url, trusted_url,
)
from afisha_bot import select, event_topic, format_event, _official_poster, event_in_window

NOW = datetime(2026, 11, 18, 12, tzinfo=ZoneInfo("Europe/Belgrade"))
LOZ_URL = "https://lozionica.rs/pojedinacni-dogadjaj/katabasis/"
LOZ_EVENT = """
<html><head><meta property="og:image" content="https://lozionica.rs/wp-content/uploads/2026/11/katabasis-poster.jpg"></head>
<body><main><article class="tribe-events-single">
<h1 class="tribe-events-single-event-title">Katabasis</h1>
<div class="tribe-events-schedule"><h2>10. Novembar 2026. @ 13:00 - 9. Decembar 2026. @ 20:00</h2></div>
<div class="tribe-events-single-event-description">
<p>Imerzivna izložba Katabasis autora Uga Arsaka, dobitnica nagrade u Kanu.
Posetioci istražuju tajni svet podzemlja Njujorka kroz interaktivne VR tehnologije.</p>
<p>Katabasis istražuje život podzemnih prolaza i svakodnevicu stanovnika velikog grada.</p>
</div>
<div class="tribe-events-event-meta">
<div class="tribe-events-event-categories">VR izložba</div>
<section><h3>CENA</h3>900 RSD</section>
</div>
<a href="https://efinity.rs/event/katabasis_2026">Kupi kartu</a>
</article></main></body></html>
"""
LOZ_POPUP = """
<html><main><h1>Katabasis Pop-up radionica</h1>
<div class="tribe-events-schedule">12. Novembar 2026. @ 18:00 - 10. Decembar 2026. @ 18:00</div>
<div class="tribe-events-single-event-description">
<p>U Ložionici učite kako da od papira napravite trodimenzionalne strukture.
Radionica namenjena deci od sedam godina, sav materijal obezbeđen.</p>
</div>
<div class="tribe-events-event-categories">Radionica</div><h3>CENA</h3>Prijavi se!
</main></html>
"""
LOZ_THEATRE = LOZ_EVENT.replace("Katabasis", "Fragmenti nasilja").replace(
    "VR izložba", "Pozorišna predstava"
).replace("10. Novembar 2026. @ 13:00 - 9. Decembar 2026. @ 20:00",
          "6. Decembar 2026. @ 20:00 - 21:30").replace("900 RSD", "RSD1200").replace(
    "Imerzivna izložba", "Pozorišna predstava"
)
AFISHA_PAGE = """
<html><body><h1>Лекции в Белграде</h1><ul>
<li>20.11.2026:
<a href="/ru/lekcii/hleb-na-serbskih-srednevekovyh-freskah-lekcia-i-degustacia-v-dome-evre-ru3368">Лекция о средневековом хлебе и дегустация</a>
· <a href="/ru/venues/dom-jevrema-grujica">Dom Jevrema Grujića</a></li>
<li>10.11.2026:
<a href="/ru/lekcii/old-interesting-lecture-before-november-ru1234">Прошедшая лекция историка</a>
· <a href="/ru/venues/dom">Auditoria</a></li>
<li>21.11.2026:
<a href="https://evil.example/ru/lekcii/long-lecture-title-here">Злонамеренный чужой сайт</a></li>
</ul></body></html>
"""


class SmallCultureTests(unittest.TestCase):
    def test_official_lozionica_exhibition_has_exact_date_range_and_price(self):
        event = loz_detail(LOZ_EVENT, LOZ_URL, NOW)
        self.assertIsNotNone(event)
        self.assertEqual(event.start.strftime("%Y-%m-%d %H:%M"), "2026-11-10 13:00")
        self.assertEqual(event.end.strftime("%Y-%m-%d %H:%M"), "2026-12-09 20:00")
        self.assertEqual(event.price, "900 дин.")
        self.assertIn("katabasis-poster.jpg", event.image)
        self.assertEqual(event.ticket_url, "https://efinity.rs/event/katabasis_2026")
        self.assertTrue(event_in_window(event, NOW))
        self.assertEqual(event_topic(event), "exhibition")
        self.assertTrue(_official_poster(event.image))

    def test_small_workshop_is_not_incorrectly_declared_free(self):
        e = loz_detail(LOZ_POPUP,
                       "https://lozionica.rs/pojedinacni-dogadjaj/katabasis-pop-up-radionica/", NOW)
        self.assertIsNotNone(e)
        self.assertEqual(e.price, "не указана")
        self.assertEqual(event_topic(e), "workshop")
        self.assertTrue(e.end.date().isoformat() == "2026-12-10")

    def test_theatre_admission_prefix_rsd(self):
        e = loz_detail(LOZ_THEATRE,
                       "https://lozionica.rs/pojedinacni-dogadjaj/fragmenti-nasilja/", NOW)
        self.assertIsNotNone(e)
        self.assertEqual(e.price, "1200 дин.")

    def test_official_links_only(self):
        items = loz_links('<a href="/pojedinacni-dogadjaj/katabasis/">True</a>'
                          '<a href="https://evil.com/pojedinacni-dogadjaj/katabasis/">Bad</a>')
        self.assertEqual(items, [LOZ_URL])
        self.assertFalse(trusted_url("https://lozionica.rs",
                                    "http://evil.example/event", "/pojedinacni-dogadjaj/"))

    def test_russian_local_listing_date_venue_and_age(self):
        found = afisha_cards(AFISHA_PAGE, NOW, "/ru/lekcii")
        self.assertEqual(len(found), 1)
        event = found[0]
        self.assertEqual(event.start.date().isoformat(), "2026-11-20")
        self.assertEqual(event.venue, "Dom Jevrema Grujića")
        self.assertEqual(event.price, "не указана")
        self.assertEqual(event_topic(event), "workshop")
        self.assertIn("Лекция", format_event(event, "Лекция о хлебе",
                                           "Лекция и дегустация в доме-музее."))
        self.assertEqual(len(select(found, {}, NOW)), 1)


    def test_kcgrad_calendar_extracts_future_unique_culture_events(self):
        from local_culture_events import kcgrad_cards
        html = """
        <main>
        <h4>Tuesday, 17th November</h4>
        <p>18:00 – Language Café</p>
        <h4>Friday, 20th November</h4>
        <p>22:00 – Sexual Friday – Episode 13: Riderz On The Storm (DJ set)</p>
        <h4>Sunday, 22nd November</h4>
        <p>12:30 – Drag Brunch</p>
        <h4>Monday, 23rd November</h4>
        <p>21:00 – Bad Music For Bad People present: Plattenbau (concert)</p>
        </main>"""
        found = kcgrad_cards(html, NOW)
        self.assertEqual(len(found), 3)
        self.assertEqual(found[0].start.strftime("%Y-%m-%d %H:%M"),
                         "2026-11-20 22:00")
        self.assertTrue(all(e.city == "Белград" for e in found))
        self.assertTrue(all(e.price == "не указана" for e in found))
        self.assertTrue(all("kcgrad.rs/calendar/" in e.url for e in found))
        self.assertEqual(found[-1].category, "Concert")

    def test_listing_does_not_rehost_unlicensed_photo(self):
        found = afisha_cards(AFISHA_PAGE, NOW, "/ru/lekcii")
        self.assertEqual(found[0].image, "")
        self.assertFalse(afisha_url("https://evil.example/ru/lekcii/long-event-2026"))


if __name__ == "__main__":
    unittest.main()
