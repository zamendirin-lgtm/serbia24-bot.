"""Official Arena and Serbian National Theatre calendar source tests."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from major_venues import arena_detail, arena_links, arena_url, snp_cards, snp_url
from afisha_bot import select

NOW = datetime(2026, 11, 16, tzinfo=ZoneInfo("Europe/Belgrade"))
A = "https://arenabeograd.com/dogadjaj/andre-rieu/"
ARENA_PAGE = """
<html><head><meta property="og:image"
content="https://arenabeograd.com/wp-content/uploads/2026/01/andre-rieu.jpg"></head>
<body><main>
<h1 class="tribe-events-single-event-title">Andre Rieu</h1>
<div class="tribe-events-schedule"><abbr title="2026-11-19">19 novembar</abbr></div>
<div class="tribe-events-single-event-description">
<p>Koncert Andre Rieua sa orkestrom Johann Strauss i valcerima,
filmskom muzikom i romantičnim melodijama u Beogradskoj areni.</p>
<a href="https://tickets.rs/event/andre_rieu_2026">Kupi ulaznice</a>
</div>
<div class="tribe-events-event-categories"><a href="/category/koncerti/">Koncerti</a></div>
</main></body></html>
"""
SNP_PAGE = """
<div class="event-card">
<h4><a href="/rs/site/eventDetail/index/4831">Carska nevesta</a></h4>
<div>Utorak, 17. novembar 2026. u 19:00 - Scena: Jovan Đorđević</div>
<div>Opera Nikolaja Rimskog Korsakova. 600,00 - 1.000,00 RSD</div>
</div>
<div class="event-card">
<h4><a href="/rs/site/eventDetail/index/4832">Revizor</a></h4>
<div>Utorak, 17. novembar 2026. u 19:30 - Scena: Pera Dobrinović</div>
<div>Komedija Nikolaja Gogolja. 1.000,00 RSD</div>
</div>
"""


class MajorVenuesTests(unittest.TestCase):
    def test_venue_links_are_source_strict(self):
        self.assertEqual(arena_url("/dogadjaj/andre-rieu/"), A)
        self.assertEqual(arena_links(
            '<a href="/dogadjaj/andre-rieu/">Andre</a>'
            '<a href="/dogadjaj/andre-rieu/">Again</a>'
            '<a href="https://example.org/dogadjaj/bad/">No</a>'), [A])
        self.assertEqual(snp_url("/rs/site/eventDetail/index/4831"),
                         "https://prodaja.snp.org.rs/rs/site/eventDetail/index/4831")
        self.assertFalse(snp_url("https://evil.test/rs/site/eventDetail/index/4831"))

    def test_arena_rieu_is_cultural(self):
        e = arena_detail(ARENA_PAGE, A, NOW)
        self.assertIsNotNone(e)
        self.assertEqual(e.start.date().isoformat(), "2026-11-19")
        self.assertIn("Арена", e.venue)
        self.assertEqual(e.price, "не указана")
        self.assertTrue(e.image.endswith("andre-rieu.jpg"))
        self.assertEqual(e.ticket_url, "https://tickets.rs/event/andre_rieu_2026")
        self.assertEqual(len(select([e], {}, NOW)), 1)

    def test_sports_event_rejected(self):
        html = ARENA_PAGE.replace("Andre Rieu", "Partizan vs Valencia EuroLeague")
        self.assertIsNone(arena_detail(html, A, NOW))

    def test_snp_orchestra_and_theatre_events(self):
        events = snp_cards(SNP_PAGE, NOW)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].start.strftime("%Y-%m-%d %H:%M"), "2026-11-17 19:00")
        self.assertEqual(events[0].city, "Нови-Сад")
        self.assertEqual(events[0].price, "от 600 дин. (по данным кассы)")
        self.assertEqual(events[0].category, "Opera")
        self.assertEqual(len(select(events, {}, NOW)), 2)


if __name__ == "__main__":
    unittest.main()
