import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from property_bot import (
    CITIES, Offer, canonical_url, format_post,
    listing_links, parse_offer, pick_cities, shortlist,
)

NOW = datetime(2026, 11, 13, 12, tzinfo=ZoneInfo("Europe/Belgrade"))
URL = "https://www.4zida.rs/izdavanje-stanova/visnjica-palilula-opstina-beograd/dvosoban-stan/6af5f528e1e48125c40e2960"
HTML = """
<html><body>
<h1>Dvosoban stan za izdavanje, Višnjica, 500€, 50m²</h1>
<p>Beograd, Palilula opština, Višnjica</p>
<p>Oglas ažuriran: 12.11.2026.</p>
<h2>Kontakt oglašivača</h2><p>Urbani Agent</p>
</body></html>"""


class RealEstateTests(unittest.TestCase):
    def test_listing_links_are_host_restricted_and_unique(self):
        page = f"""<a href="{URL}">Apartment</a>
        <a href="{URL}?tracking=1">Again</a>
        <a href="https://malicious.example/izdavanje-stanova/bg/a/{'a'*24}">Ignore</a>
        """
        self.assertEqual(listing_links(page, "izdavanje-stanova"), [URL])

    def test_parse_price_area_date(self):
        offer = parse_offer(HTML, URL, "beograd", "izdavanje-stanova", NOW)
        self.assertIsNotNone(offer)
        self.assertEqual(offer.price_eur, 500)
        self.assertEqual(offer.area_m2, 50)
        self.assertEqual(offer.updated, "2026-11-12")

    def test_old_ad_rejected(self):
        self.assertIsNone(parse_offer(HTML.replace("12.11.2026", "01.09.2026"),
                                      URL, "beograd", "izdavanje-stanova", NOW))

    def test_rent_and_sale_price_thresholds(self):
        o1 = Offer(URL, "Белград", "izdavanje-stanova", "Test", 400, 50, "2026-11-12")
        o2 = Offer("https://www.4zida.rs/prodaja-stanova/bg/a/"+"b"*24,
                   "Ниш", "prodaja-stanova", "Test", 90000, 55, "2026-11-12")
        self.assertEqual(shortlist([o1, o2], {}, 2), [o1, o2])
        self.assertEqual(shortlist([o1], {o1.key: {"posted_at": NOW.isoformat()}}), [])

    def test_publication_attributes_and_provenance(self):
        offer = parse_offer(HTML, URL, "beograd", "izdavanje-stanova", NOW)
        output = format_post(offer, NOW)
        self.assertIn("500 €", output)
        self.assertIn("Не указан", output)
        self.assertIn("Доступность и документы не подтверждены", output)
        self.assertIn("https://www.4zida.rs/", output)

    def test_cities_rotation(self):
        self.assertEqual(len(pick_cities(NOW)), 2)
        self.assertTrue(set(pick_cities(NOW)).issubset(set(CITIES)))

    def test_external_link_rejected(self):
        self.assertEqual(canonical_url("https://evil.example/yes"), "")


if __name__ == "__main__":
    unittest.main()
