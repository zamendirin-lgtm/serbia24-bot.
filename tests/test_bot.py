import unittest
from unittest.mock import Mock
from datetime import timedelta
from unittest.mock import patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot import (
    Article, canonical_url, format_post, is_duplicate, normalized_title,
    foreign_centered_story,
    parse_feed, recent_enough, relevant, post_telegram, prepare_summary, photo_caption, rss_photo, normal_image_url,
    same_event_title, event_terms, prune_state, publication_allowed,
    interval_allows_publication, next_eligible_publication, MIN_PUBLICATION_INTERVAL_MINUTES,
    branded_fallback_photo, extract_article_paragraphs, select_news_paragraphs,
    financial_exception_context,
    national_culture_award_context,
    film_premiere_context,
    translate_article, complete_sentences_for_budget,
    image_dhash, photo_url_key, is_repeated_photo,
    news_interest_score, rank_news, price_figure, is_price_story, MIN_INTEREST_SCORE,
    major_national_story, public_safety_breaking_story,
    major_incident_story, material_economic_proposal,
    significant_medical_opening, major_cultural_announcement,
    major_infrastructure_milestone, benchmark_news_category,
    parliamentary_milestone_stage, different_parliamentary_milestones,
)


class NewsBotTests(unittest.TestCase):
    def test_cyrillic_transliteration(self):
        self.assertEqual(normalized_title("Београд"), "beograd")

    def test_remove_tracking_parameters(self):
        self.assertEqual(
            canonical_url("https://rts.rs/news/?utm_source=x&id=2#section"),
            "https://rts.rs/news?id=2",
        )

    def test_parliament_majority_confirmation_must_not_score_zero(self):
        ts = datetime.now(timezone.utc).timestamp()
        a = Article(
            "N1", "Potvrđena nova većina u Skupštini Srbije",
            "https://n1info.rs/vesti/vecina-2026",
            "Na sednici potvrđeni mandati, Studentska lista ima 140 mesta.",
            ts - 300,
        )
        self.assertTrue(relevant(a))
        self.assertTrue(major_national_story(a))
        self.assertGreaterEqual(
            news_interest_score(a, datetime.fromtimestamp(ts, timezone.utc)), 15
        )

    def test_inaugural_session_and_new_government_are_important(self):
        ts = datetime.now(timezone.utc).timestamp()
        names = [
            "Danas konstitutivna sednica Skupštine Srbije",
            "Poslanici Skupštine Srbije položili zakletvu",
            "Srbija dobija novu vlast",
            "Izabrana nova vlada Srbije",
        ]
        for index, title in enumerate(names):
            with self.subTest(title=title):
                a = Article("RTS", title,
                            f"https://rts.rs/vesti/politika/major-{index}",
                            "", ts)
                self.assertTrue(major_national_story(a))
                self.assertGreaterEqual(
                    news_interest_score(a, datetime.fromtimestamp(ts, timezone.utc)),
                    15,
                )

    def test_parliament_cafes_not_mistaken_for_historic_decision(self):
        now = datetime.now(timezone.utc)
        article = Article(
            "N1",
            '"Da podelimo ovu radost": Novosadski kafići puni od ranog jutra, prati se konstitutivna sednica Skupštine',
            "https://n1info.rs/vesti/kafici",
            "Ljudi gledaju prenos Skupštine iz kafica.",
            now.timestamp()
        )
        self.assertFalse(major_national_story(article))
        self.assertLess(news_interest_score(article, now), 15)

    def test_article_about_interest_in_parliament_is_not_official_event(self):
        now = datetime.now(timezone.utc)
        article = Article(
            "N1",
            "AP: Veliko interesovanje za konstitutivnu sednicu Skupštine Srbije",
            "https://n1info.rs/vesti/reakcija",
            "Građani prate početak rada parlamenta.",
            now.timestamp()
        )
        self.assertFalse(major_national_story(article))

    def test_obituary_hero_profile_not_mistaken_for_new_crash(self):
        now = datetime.now(timezone.utc)
        article = Article(
            "B92",
            "Poginuli major Goran Bulajić bio je heroj Srbije kada je Obrenovac bio pod vodom",
            "https://b92.net/vesti/pilot-heroj", "",
            now.timestamp()
        )
        self.assertFalse(public_safety_breaking_story(article))

    def test_major_news_rank_above_minor_price_notice_and_seminar(self):
        ts = datetime.now(timezone.utc).timestamp()
        political = Article(
            "RTS", "Potvrđena nova većina u Skupštini Srbije",
            "https://rts.rs/politika/vecina", "", ts - 800,
        )
        tiny = Article(
            "Danas", "Cena parkinga u Srbiji povećana za 1 dinar",
            "https://danas.rs/parking", "", ts - 50,
        )
        seminar = Article(
            "Danas", "Radionica o koncentraciji u Kragujevcu",
            "https://danas.rs/radionica", "", ts - 30,
        )
        ordered = rank_news([seminar,tiny,political],
                            datetime.fromtimestamp(ts, timezone.utc))
        self.assertEqual(ordered[0], political)

    def test_new_parliament_oath_not_same_as_morning_session_announcement(self):
        now = datetime.now(timezone.utc).timestamp()
        old = "BLOG: Danas konstitutivna sednica Skupštine Srbije"
        stage = "Poslanici Skupštine Srbije položili zakletvu"
        self.assertEqual(parliamentary_milestone_stage(old), "opening")
        self.assertEqual(parliamentary_milestone_stage(stage), "constituted")
        self.assertTrue(different_parliamentary_milestones(stage, old))
        a = Article("N1", stage, "https://n1info.rs/skupstina-zakletva",
                    "Potvrđeni mandati 250 narodnih poslanika.",now)
        state = {"seen": {}, "posted": [{
            "title_norm": normalized_title(old),
            "summary_norm": normalized_title("Danas počela konstitutivna sednica."),
            "source": "RTS", "ts": now - 2*3600
        }]}
        self.assertFalse(is_duplicate(a, state))

    def test_confirmed_majority_after_oath_same_day_is_duplicate(self):
        now = datetime.now(timezone.utc).timestamp()
        established = "Poslanici Skupštine Srbije položili zakletvu"
        later = Article(
            "RTS", "Potvrđena nova većina u Skupštini Srbije",
            "https://rts.rs/politika/nova-vecina", "", now + 3600
        )
        state = {"seen": {}, "posted": [{
            "title_norm": normalized_title(established),
            "source": "Tanjug", "ts": now,
        }]}
        self.assertEqual(
            parliamentary_milestone_stage(later.title), "constituted"
        )
        self.assertTrue(is_duplicate(later, state))

    def test_repeated_coverage_of_same_oath_is_still_duplicate(self):
        now = datetime.now(timezone.utc).timestamp()
        old = "Poslanici Skupštine Srbije položili zakletvu"
        a = Article(
            "N1", "Skupština Srbije: poslanici položili zakletvu",
            "https://n1info.rs/vesti/zakletva", "", now
        )
        state = {"seen": {}, "posted": [{
            "title_norm": normalized_title(old),
            "source": "RTS", "ts": now - 60
        }]}
        self.assertFalse(different_parliamentary_milestones(a.title, old))
        self.assertTrue(is_duplicate(a, state))

    def test_fatal_pilot_plane_crash_is_a_major_domestic_story(self):
        ts = datetime.now(timezone.utc).timestamp()
        a = Article(
            "N1", "Poginuo pilot Vojske Srbije u padu aviona Mig-29",
            "https://n1info.rs/vesti/avion", "", ts
        )
        self.assertTrue(public_safety_breaking_story(a))
        self.assertGreaterEqual(
            news_interest_score(a, datetime.fromtimestamp(ts, timezone.utc)), 10
        )

    def test_reader_examples_six_categories_are_relevant_and_high_priority(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        cases = [
            ("serious_incident",
             "Više od 15 dece povređeno na pokretnim stepenicama u tržnom centru Galerija u Beogradu",
             "Hitna pomoć stigla u Beograd.", 18),
            ("serious_incident",
             "Srušio se vojni avion kod Stare Pazove",
             "Policija i hitna pomoć na mestu nesreće kod Stare Pazove.", 18),
            ("economic_proposal",
             "Studentska lista predstavila ekonomski program: porez na nekretnine",
             "Predlog novih poreskih mera u Srbiji.", 12),
            ("healthcare_opening",
             "Prvi specijalizovani centar za buloznu epidermolizu otvoren u Beogradu",
             "Klinika u Beogradu primaće pacijente.", 12),
            ("major_festival",
             "EXIT objavio datume povratka u Novi Sad: festival od 1. do 4. jula 2027",
             "U Novom Sadu će biti organizovan festival.", 10),
            ("major_infrastructure",
             "EXPO 2027: Paviljoni se predaju učesnicima od 1. decembra",
             "Gradilište u Surčinu kraj Beograda.", 12),
        ]
        for i, (expected_category, title, summary, minimum) in enumerate(cases):
            with self.subTest(title=title):
                item = Article("RTS", title,
                               f"https://rts.rs/test/readers-example-{i}",
                               summary, now.timestamp() - 300)
                self.assertTrue(relevant(item))
                self.assertEqual(benchmark_news_category(item), expected_category)
                self.assertGreaterEqual(news_interest_score(item, now), minimum)

    def test_first_center_not_mistaken_for_any_clinic_mention(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        first = Article(
            "RTS", "U Beogradu otvoren prvi specijalizovani centar za retke bolesti",
            "https://rts.rs/first", "", now.timestamp()
        )
        routine = Article(
            "RTS", "Doktor je govorio o pregledu u bolnici u Beogradu",
            "https://rts.rs/routine", "", now.timestamp()
        )
        self.assertTrue(significant_medical_opening(first))
        self.assertFalse(significant_medical_opening(routine))
        self.assertGreater(news_interest_score(first, now), news_interest_score(routine, now))

    def test_minor_concert_stays_below_major_exit_announcement(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        exit_story = Article(
            "021", "EXIT se vraća u Novi Sad 2027: najavljeni datumi festivala",
            "https://021.rs/exit", "Festival u Novom Sadu.", now.timestamp()
        )
        small = Article(
            "Danas", "Lokalni koncert u Beogradu u kafiću večeras",
            "https://danas.rs/koncert", "", now.timestamp()
        )
        self.assertTrue(major_cultural_announcement(exit_story))
        self.assertFalse(major_cultural_announcement(small))
        self.assertGreater(news_interest_score(exit_story, now),
                           news_interest_score(small, now))

    def test_economic_proposal_is_not_automatically_an_enacted_law(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        article = Article(
            "N1", "Studentska lista predlaže ekonomski program: porez na nekretnine",
            "https://n1info.rs/program", "Predlog za građane Srbije.", now.timestamp(),
        )
        self.assertFalse(major_national_story(article))
        self.assertTrue(material_economic_proposal(article))

    def test_foreign_expo_without_serbia_link_stays_excluded(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        article = Article(
            "Danas", "EXPO 2027 u Japanu: pripreme za svetski sajam",
            "https://danas.rs/foreign-expo", "Sajam u Japanu.", now.timestamp(),
        )
        self.assertFalse(relevant(article))

    def test_incidents_without_factual_support_not_manufactured(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        news = Article(
            "N1", "Pad vojnog aviona kod Stare Pazove: istraga u toku",
            "https://n1info.rs/plane", "Još nema potvrde o žrtvama.", now.timestamp(),
        )
        self.assertTrue(major_incident_story(news))
        # Scores indicate priority, not evidence about injuries, aircraft type,
        # deaths, victims or official causes.
        self.assertNotIn("poginu", normalized_title(news.title))

    def test_reader_interest_prioritizes_real_prices_over_sports(self):
        ts = datetime.now(timezone.utc).timestamp()
        prices = Article(
            "Danas", "Nove cene goriva u Srbiji: dizel 236 dinara, benzin 207 dinara",
            "https://danas.rs/prices", "Cene važe do narednog petka.", ts - 3600,
        )
        sports = Article(
            "B92", "Srbija igra utakmicu protiv Nemačke u Ligi nacija",
            "https://b92.net/sport", "Prenos utakmice biće danas uveče.", ts - 200,
        )
        now = datetime.fromtimestamp(ts, timezone.utc)
        self.assertTrue(is_price_story(prices))
        self.assertTrue(price_figure(prices.title))
        self.assertGreater(news_interest_score(prices, now), news_interest_score(sports, now))
        self.assertEqual(rank_news([sports, prices], now)[0].url, prices.url)
        self.assertLess(news_interest_score(sports, now), MIN_INTEREST_SCORE)

    def test_practical_legal_change_more_important_than_seminar(self):
        ts = datetime.now(timezone.utc).timestamp()
        practical = Article(
            "RTS", "Novi zakon u Srbiji menja postupak izdavanja ličnih karata",
            "https://rts.rs/zakon", "Nove izmene važe od decembra.", ts - 3000,
        )
        filler = Article(
            "Danas", "Radionica o koncentraciji u Omladinskom klubu Kragujevca",
            "https://danas.rs/radionica", "", ts - 50,
        )
        now = datetime.fromtimestamp(ts, timezone.utc)
        self.assertGreater(news_interest_score(practical, now), news_interest_score(filler, now))
        self.assertEqual(rank_news([filler, practical], now)[0], practical)

    def test_police_losses_not_misidentified_as_consumer_price(self):
        ts = datetime.now(timezone.utc).timestamp()
        story = Article(
            "RTS", "U Novom Sadu uhapšen direktor zbog zloupotrebe",
            "https://rts.rs/policija",
            "Sumnja se na štetu od 2,7 miliona dinara.",
            ts,
        )
        self.assertFalse(is_price_story(story))
        self.assertFalse(price_figure("Steta 2026. godine"))
        self.assertTrue(price_figure("Cena je 250 dinara."))
        self.assertTrue(price_figure("Цена 250 динара."))

    def test_extract_price_amount_even_if_after_first_paragraphs(self):
        blocks = [
            "Cene goriva u Srbiji ostaju nepromenjene tokom ove nedelje, saopštilo je ministarstvo nadležno za trgovinu.",
            "Odluka se odnosi na prodaju benzina i dizela na pumpama u celoj zemlji i važi narednih sedam dana.",
            "Ministarstvo je navelo da se primenjuje ograničenje najviše maloprodajne cene derivata nafte.",
            "Maksimalna cena evrodizela biće 236 dinara za litar, dok će benzin BMB 95 koštati 207 dinara po litru.",
        ]
        selected = select_news_paragraphs(blocks, "Nove cene goriva u Srbiji")
        self.assertGreaterEqual(len(selected), 2)
        self.assertIn("236 dinara", " ".join(selected))
        self.assertIn("207 dinara", " ".join(selected))

    def test_rank_relevance_prefers_fresh_breaking_changes_over_old_announcement(self):
        ts = datetime.now(timezone.utc).timestamp()
        now = datetime.fromtimestamp(ts, timezone.utc)
        a = Article("Danas", "Cene hrane u Srbiji", "https://danas.rs/old", "", ts - 7*3600)
        b = Article("N1", "Cene hrane u Srbiji", "https://n1.rs/new", "", ts - 600)
        self.assertGreater(news_interest_score(b, now), news_interest_score(a, now))

    def test_local_filter(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertTrue(relevant(
            Article("RTS", "Cene goriva u Srbiji", "https://rts.rs/a", "", now)
        ))
        self.assertFalse(relevant(
            Article("N1", "New York sports match", "https://n1info.rs/b", "", now)
        ))

    def test_tokyo_population_story_mentioning_serbia_as_comparison_is_rejected(self):
        article = Article(
            "Danas",
            "Može da stane u Srbiju šest i po puta, a ima 37 miliona stanovnika: Ovo je Veliki Tokio",
            "https://www.danas.rs/zivot/moze-da-stane-u-srbiju-sest-i-po-puta-a-ima-37-miliona-stanovnika-ovo-je-veliki-tokio/",
            "Veliki Tokio čine Tokio i tri susedne prefekture Kanagava, Saitama i Čiba; u Srbiji bi mogao da stane šest puta.",
            datetime.now(timezone.utc).timestamp(),
        )
        self.assertTrue(foreign_centered_story(article))
        self.assertFalse(relevant(article))

    def test_foreign_city_in_headline_without_serbian_subject_is_rejected(self):
        article = Article(
            "Danas",
            "Veliki Tokio broji skoro 37 miliona ljudi, više nego u Srbiji",
            "https://danas.rs/zivot/tokio/",
            "Japanska gradska regija obuhvata nekoliko prefektura.",
            datetime.now(timezone.utc).timestamp(),
        )
        self.assertFalse(relevant(article))

    def test_comparison_with_paris_is_not_local_news(self):
        a = Article(
            "Danas", "Pariz može da stane u Srbiju hiljadu puta",
            "https://danas.rs/zivot/pariz",
            "Francuska prestonica ima mnogo stanovnika.", 0,
        )
        self.assertFalse(relevant(a))

    def test_serbian_japanese_agreement_still_relevant(self):
        article = Article(
            "RTS", "Srbija i Japan potpisali sporazum o saradnji",
            "https://rts.rs/vesti/srbija-japan",
            "Sporazum je potpisan u Beogradu.",
            datetime.now(timezone.utc).timestamp(),
        )
        self.assertFalse(foreign_centered_story(article))
        self.assertTrue(relevant(article))

    def test_japanese_investment_in_serbia_remains_relevant(self):
        article = Article(
            "RTS", "Japan investira u Srbiju u novi pogon za auto-delove",
            "https://rts.rs/vesti/japan-investira",
            "U Srbiju dolazi nova investicija i planirana su radna mesta.",
            datetime.now(timezone.utc).timestamp(),
        )
        self.assertFalse(foreign_centered_story(article))
        self.assertTrue(relevant(article))

    def test_local_japanese_company_in_belgrade_still_relevant(self):
        article = Article(
            "RTS", "Japanska kompanija otvorila fabriku u Beogradu",
            "https://rts.rs/vesti/fabrika",
            "Nova fabrika zaposliće radnike u Srbiji.",
            datetime.now(timezone.utc).timestamp(),
        )
        self.assertTrue(relevant(article))

    def test_serbia_travel_rules_for_japan_still_relevant(self):
        a = Article(
            "N1", "U Srbiji uvedena nova pravila putovanja u Japan",
            "https://n1info.rs/srbija/japan",
            "Nova pravila važe za putnike iz Srbije.", 0,
        )
        self.assertTrue(relevant(a))

    def test_spain_news_is_not_serbian_news(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertFalse(relevant(
            Article("Danas",
                    "Veliki protesti širom Španije zbog problema sa stanovanjem, samo u Madridu 120.000 ljudi",
                    "https://www.danas.rs/a",
                    "U Srbiji se takođe govori o protestima i pravima građana.", now)
        ))

    def test_serbian_story_quoting_foreign_media_is_local(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertTrue(relevant(
            Article("N1", "Američki časopis o pobedi studenata u Srbiji",
                    "https://n1info.rs/a", "", now)
        ))

    def test_90_minute_gap_after_latest_post(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        prior = now.timestamp() - 89 * 60
        state = {"posted": [{"ts": prior, "title_norm": "news", "source": "RTS"}]}
        self.assertEqual(MIN_PUBLICATION_INTERVAL_MINUTES, 90)
        self.assertFalse(interval_allows_publication(state, now))
        self.assertEqual(
            next_eligible_publication(state, now),
            datetime.fromtimestamp(prior + 90 * 60, timezone.utc)
        )
        later = now + timedelta(minutes=1)
        self.assertTrue(interval_allows_publication(state, later))

    def test_gap_is_based_on_most_recent_successful_post(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        state = {"posted": [
            {"ts": now.timestamp() - 240 * 60, "source": "RTS"},
            {"ts": now.timestamp() - 45 * 60, "source": "N1"},
            {"ts": now.timestamp() - 110 * 60, "source": "Danas"},
        ]}
        self.assertFalse(interval_allows_publication(state, now))
        self.assertTrue(interval_allows_publication(state, now + timedelta(minutes=45)))

    def test_empty_history_allows_publication(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(interval_allows_publication({"posted": []}, now))
        self.assertIsNone(next_eligible_publication({"posted": []}, now))

    def test_overnight_gap_and_quiet_hours_both_apply(self):
        zone = ZoneInfo("Europe/Belgrade")
        last_evening = datetime(2026, 11, 12, 21, 50, tzinfo=zone)
        state = {"posted": [{"ts": last_evening.timestamp(), "source": "N1"}]}
        at_seven = datetime(2026, 11, 13, 7, 30, tzinfo=zone)
        at_eight = datetime(2026, 11, 13, 8, 0, tzinfo=zone)
        self.assertTrue(interval_allows_publication(state, at_seven))
        self.assertFalse(publication_allowed(at_seven))
        self.assertTrue(interval_allows_publication(state, at_eight))
        self.assertTrue(publication_allowed(at_eight))

    def test_no_night_publications_belgrade_winter(self):
        zone = ZoneInfo("Europe/Belgrade")
        for hour in (22, 23, 0, 1, 7):
            local = datetime(2026, 11, 12 if hour > 7 else 13, hour, 30, tzinfo=zone)
            self.assertFalse(publication_allowed(local), f"should block {hour}")
        for hour in (8, 9, 21):
            local = datetime(2026, 11, 12, hour, 30, tzinfo=zone)
            self.assertTrue(publication_allowed(local), f"should permit {hour}")

    def test_no_night_publications_belgrade_summer(self):
        zone = ZoneInfo("Europe/Belgrade")
        for hour in (0, 7, 22, 23):
            self.assertFalse(publication_allowed(datetime(2026, 7, 12, hour, 0, tzinfo=zone)))
        for hour in (8, 20, 21):
            self.assertTrue(publication_allowed(datetime(2026, 7, 12, hour, 0, tzinfo=zone)))

    def test_trump_iran_not_serbia(self):
        a = Article("N1",
            "Tramp: SAD nisu započele rat sa Iranom, Teheran vodi rat protiv Amerike",
            "https://n1info.rs/iran", "Donald Trump je izjavio.", 0)
        self.assertFalse(relevant(a))

    def test_nis_is_not_nisu(self):
        a = Article("N1", "U Nišu počela izgradnja nove bolnice",
                    "https://n1info.rs/nis", "", 0)
        self.assertTrue(relevant(a))
        unrelated = Article("N1", "Političari nisu zadovoljni novim izborima u Francuskoj",
                            "https://n1info.rs/a", "", 0)
        self.assertFalse(relevant(unrelated))

    def test_kosovo_local_protest_excluded(self):
        a = Article("Danas",
            "U Zubinom Potoku na severu Kosova protest porodica uhapšenih Srba u slučaju Dosije 23",
            "https://www.danas.rs/kosovo", "U Srbiji su svi pratili vest", 0)
        self.assertFalse(relevant(a))

    def test_kosovo_official_serbian_statement_allowed(self):
        a = Article("RTS", "Vučić o situaciji na Kosovu: Vlada Srbije objavila mere",
                    "https://www.rts.rs/vest", "", 0)
        self.assertTrue(relevant(a))

    def test_summary_discards_source_questions(self):
        a = Article("RTS", "Ekspo u Srbiji", "https://rts.rs/a",
             "Međunarodne manifestacije donose ekonomsku korist. "
             "Međutim, neki građani kritikuju troškove izložbe. "
             "Kako za 93 dana predstaviti Srbiju i privući turiste?", 0)
        summary = prepare_summary(a)
        self.assertNotIn("Kako za", summary)
        self.assertNotIn("?", summary)
        self.assertIn("Međutim", summary)

    def test_image_identical_pixels_different_file_encodings(self):
        from io import BytesIO
        from PIL import Image
        im = Image.new("RGB", (42, 30), "white")
        for y in range(12):
            for x in range(26):
                im.putpixel((x, y), (20, 30, 70))
        a = BytesIO()
        b = BytesIO()
        im.save(a, format="PNG")
        im.save(b, format="JPEG", quality=80)
        # JPEG compression can flip one or two dHash bits; near-identical
        # photographs must still count as duplicates.
        distance = (int(image_dhash(a.getvalue()), 16) ^ int(image_dhash(b.getvalue()), 16)).bit_count()
        self.assertLessEqual(distance, 3)

    def test_repeated_photo_url_and_hash(self):
        now = datetime.now(timezone.utc).timestamp()
        url = "https://www.danas.rs/images/interview.png"
        state = {"photos": {photo_url_key(url): now}, "phashes": {"abcda98765ef4321": now}}
        self.assertTrue(is_repeated_photo(url, "", state))
        self.assertTrue(is_repeated_photo(
            "https://www.danas.rs/images/another.jpg", "abcda98765ef4321", state
        ))
        self.assertFalse(is_repeated_photo(
            "https://www.danas.rs/images/new.jpg", "1234567890abcdef", state
        ))

    def test_prune_photo_history(self):
        now = datetime.now(timezone.utc)
        state = {"seen": {}, "posted": [], "photos": {
                    "recent": (now - timedelta(days=15)).timestamp(),
                    "old": (now - timedelta(days=70)).timestamp()},
                 "phashes": {
                    "abcda98765ef4321": (now - timedelta(days=8)).timestamp(),
                    "abcda98765ef4320": (now - timedelta(days=90)).timestamp()}}
        prune_state(state, now)
        self.assertEqual(list(state["photos"]), ["recent"])
        self.assertEqual(list(state["phashes"]), ["abcda98765ef4321"])

    def test_recent_articles(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(recent_enough(
            Article("RTS", "News", "https://rts.rs/1", "", now.timestamp() - 7200), now
        ))
        self.assertFalse(recent_enough(
            Article("RTS", "Old", "https://rts.rs/2", "", now.timestamp() - 36000), now
        ))

    def test_near_duplicate_title(self):
        now = datetime.now(timezone.utc).timestamp()
        a = Article("RTS", "Скупштина Србије донела нови закон", "https://rts.rs/a", "", now)
        state = {
            "seen": {},
            "posted": [{"title_norm": normalized_title(
                "Skupstina Srbije donela novi zakon"
            ), "ts": now}],
        }
        self.assertTrue(is_duplicate(a, state))

    def test_duplicate_same_news_different_order(self):
        now = datetime.now(timezone.utc).timestamp()
        previous = Article(
            "RTS", "Drekslmajer zatvara fabriku u Zrenjaninu",
            "https://www.rts.rs/vesti/stara", "", now,
        )
        later = Article(
            "Danas", "U Zrenjaninu kompanija Drekslmajer zatvara fabriku",
            "https://www.danas.rs/vesti/nova", "", now,
        )
        state = {"seen": {}, "posted": [
            {"ts": now, "title_norm": normalized_title(previous.title), "source": "RTS"}
        ]}
        self.assertTrue(is_duplicate(later, state))

    def test_duplicate_same_news_reordered_price_headline(self):
        self.assertTrue(same_event_title(
            normalized_title("Cene goriva u Srbiji povećane od petka"),
            normalized_title("Od petka povećane cene goriva u Srbiji"),
        ))

    def test_cyrillic_vs_latin_duplicate(self):
        self.assertTrue(same_event_title(
            normalized_title("Зрењанин: Дрекслмајер затвара фабрику"),
            normalized_title("Drekslmajer zatvara fabriku u Zrenjaninu"),
        ))

    def test_different_prices_are_not_duplicated(self):
        self.assertFalse(same_event_title(
            normalized_title("Cena dizela u Srbiji 195 dinara"),
            normalized_title("Cena dizela u Srbiji 199 dinara"),
        ))

    def test_denial_is_not_same_as_affirmation(self):
        self.assertFalse(same_event_title(
            normalized_title("Fabrika u Zrenjaninu neće se zatvoriti"),
            normalized_title("Fabrika u Zrenjaninu se zatvoriti"),
        ))

    def test_different_accidents_same_city(self):
        self.assertFalse(same_event_title(
            normalized_title("Saobraćajna nesreća u Beogradu: troje povređeno"),
            normalized_title("Nova saobraćajna nesreća u Beogradu, dve osobe povređene"),
        ))

    def test_similar_topic_but_different_event(self):
        self.assertFalse(same_event_title(
            normalized_title("U Beogradu otvorena nova bolnica"),
            normalized_title("U Beogradu zatvorena nova bolnica"),
        ))

    def test_store_history_60_days(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=45)).timestamp()
        old = (now - timedelta(days=62)).timestamp()
        state = {
            "seen": {"recent": recent, "old": old},
            "posted": [{"ts": recent, "title_norm": "recent"},
                       {"ts": old, "title_norm": "old"}],
        }
        prune_state(state, now)
        self.assertEqual(list(state["seen"]), ["recent"])
        self.assertEqual([item["title_norm"] for item in state["posted"]], ["recent"])

    def test_low_information_titles_not_false_duplicate(self):
        self.assertFalse(same_event_title(
            normalized_title("Novi zakon u Srbiji o porezu"),
            normalized_title("Novi zakon u Srbiji o platama"),
        ))

    def test_html_escape(self):
        a = Article(
            "RTS", "Original", "https://rts.rs/a?x=2&y=3", "",
            datetime.now(timezone.utc).timestamp(),
        )
        msg = format_post(a, "Тест <b>", "Описание & детали")
        self.assertIn("&lt;b&gt;", msg)
        self.assertIn("&amp;", msg)

    def test_rss_parsing(self):
        rss = b'''<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Cene u Srbiji</title><link>https://example.com/news</link>
        <pubDate>Wed, 11 Nov 2026 14:00:00 GMT</pubDate>
        <description>Nova odluka o cenama.</description></item></channel></rss>'''
        self.assertEqual(len(parse_feed("test", rss)), 1)


    def test_news_style_branding(self):
        item = Article(
            "RTS", "Cene u Srbiji", "https://rts.rs/a", "",
            datetime.now(timezone.utc).timestamp(),
        )
        post = format_post(item, "Цены в Сербии изменились", "Первая деталь. Вторая деталь. Третья деталь.")
        self.assertIn("<b>Цены в Сербии изменились</b>", post)
        self.assertNotIn("Сербия 24", post)
        self.assertNotIn("#НовостиСербии", post)
        self.assertIn("Источник: RTS", post)
        self.assertIn("\n\n", post)
        self.assertNotIn("https://example.com", post)

    def test_telegram_sends_photo_without_english_page_preview(self):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"ok": True}
        with patch("bot.requests.post", return_value=FakeResponse()) as send:
            post_telegram(
                "Тест", "not-a-real-token", "@testchannel",
                "https://rts.rs/a", "https://rts.rs/photo.jpg", "Подпись по-русски",
            )
            self.assertIn("/sendPhoto", send.call_args.args[0])
            payload = send.call_args.kwargs["json"]
            self.assertEqual(payload["photo"], "https://rts.rs/photo.jpg")
            self.assertEqual(payload["caption"], "Подпись по-русски")
            self.assertNotIn("link_preview_options", payload)

    def test_fallback_uses_real_image_not_text_message(self):
        class Failure:
            status_code = 400
            def json(self):
                return {"ok": False, "description": "Bad source photo"}
        class Success:
            status_code = 200
            def json(self):
                return {"ok": True}

        with patch("bot.requests.post", side_effect=[Failure(), Success()]) as send, \
                patch("bot._telegram_channel_avatar", return_value=b""):
            sent_original = post_telegram(
                "Тест", "not-a-real-token", "@testchannel",
                "https://rts.rs/a", "https://rts.rs/photo.jpg", "Подпись по-русски",
            )
            self.assertFalse(sent_original)
            self.assertEqual(send.call_count, 2)
            self.assertIn("/sendPhoto", send.call_args.args[0])
            payload = send.call_args.kwargs
            self.assertIn("files", payload)
            self.assertEqual(payload["data"]["caption"], "Подпись по-русски")

    def test_branded_fallback_is_jpeg_16_9(self):
        from io import BytesIO
        from PIL import Image
        with patch("bot._telegram_channel_avatar", return_value=b""):
            data = branded_fallback_photo("not-a-real-token", "@testchannel")
        self.assertTrue(data.startswith(b"\xff\xd8"))
        with Image.open(BytesIO(data)) as im:
            self.assertEqual(im.size, (1200, 675))

    def test_no_source_photo_never_uses_send_message(self):
        class Success:
            status_code = 200
            def json(self):
                return {"ok": True}
        with patch("bot.requests.post", return_value=Success()) as send, \
                patch("bot._telegram_channel_avatar", return_value=b""):
            post_telegram(
                "Текст", "not-a-real-token", "@testchannel",
                "https://rts.rs/a", "", "Подпись по-русски",
            )
            self.assertIn("/sendPhoto", send.call_args.args[0])
            self.assertNotIn("/sendMessage", send.call_args.args[0])

    def test_photo_caption_russian(self):
        item = Article("RTS", "Original", "https://rts.rs/a", "", 0)
        caption = photo_caption(item, "Заголовок", "Первое предложение.")
        self.assertIn("Заголовок", caption)
        self.assertNotIn("Сербия 24", caption)
        self.assertNotIn("#НовостиСербии", caption)
        self.assertIn("Источник: RTS", caption)
        self.assertNotIn("Original", caption)

    def test_reject_youtube_embed_as_news_photo(self):
        fake = "https://www.youtube.com/embed/XNxSvHuHthQ"
        self.assertEqual(normal_image_url(fake), "")
        import feedparser
        entry = feedparser.parse("""<rss version="2.0"><channel><item>
          <title>U Beogradu uhapšena tri lica</title>
          <link>https://www.danas.rs/vesti/beograd/123</link>
          <description><![CDATA[<iframe src="https://www.youtube.com/embed/XNxSvHuHthQ"></iframe>
          <img src="https://www.youtube.com/embed/XNxSvHuHthQ">]]></description>
          </item></channel></rss>""").entries[0]
        self.assertEqual(rss_photo(entry, "https://www.danas.rs/vesti/beograd/123"), "")

    def test_regular_publisher_photo_still_allowed(self):
        self.assertEqual(
            normal_image_url("https://www.danas.rs/wp-content/uploads/2026/11/photo.jpg"),
            "https://www.danas.rs/wp-content/uploads/2026/11/photo.jpg",
        )

    def test_rss_media_image(self):
        import feedparser
        entry = feedparser.parse("""<rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0">
          <channel><item><title>Test</title><link>https://rts.rs/article</link>
          <media:content url="https://rts.rs/photos/a.jpg" type="image/jpeg"/>
          </item></channel></rss>""").entries[0]
        self.assertEqual(rss_photo(entry, "https://rts.rs/article"), "https://rts.rs/photos/a.jpg")

    def test_arts_award_before_after_five_ten_preserved(self):
        headline = (
            "Selakoviću proširena ovlašćenja za nacionalne penzije: "
            "Ministarstvo ranije odbilo Bošković, Savina i Kovačevića"
        )
        source = [
            "Udruženje dramskih umetnika Srbije ponovo je predložilo Tanju Bošković, Egona Savina i Sinišu Kovačevića za nacionalne penzije.",
            "Udruženje je od nadležnog ministarstva zatražilo da se odlučivanje odloži do formiranja nove vlade.",
            "Izmene uredbe iz septembra proširile su ovlašćenja ministra kulture u postupku dodele nacionalnih priznanja.",
            "Prethodna odredba dozvoljavala je ministru da predloži do pet umetnika, dok nova dozvoljava deset kandidata.",
        ]
        context = national_culture_award_context(source, headline)
        self.assertIn("pet umetnika", context)
        self.assertIn("deset kandidata", context)
        selected = select_news_paragraphs(source, headline)
        self.assertIn("pet umetnika", " ".join(selected))
        self.assertLessEqual(len(selected), 3)

    def test_no_arts_award_context_made_up_without_source(self):
        headline = "Selaković o nacionalnim penzijama"
        source = [
            "Udruženje dramskih umetnika Srbije ponovo je predložilo kandidature.",
            "Ministarstvo kulture razmatra dostavljene predloge tokom decembra.",
        ]
        self.assertEqual(national_culture_award_context(source, headline), "")

    def test_financial_exception_30_60_days_extracted_from_deeper_source(self):
        headline = "NBS menja pravila za menjače: do 60 dana za prodaju efektive bankama"
        blocks = [
            "Narodna banka Srbije izmenila je pravila za poslovanje menjačnica, što se odnosi na prodaju efektivnog stranog novca bankama.",
            "Prema novim odredbama, menjači koji kupe efektivu od banaka mogu da je vrate banci u roku od 30 dana od kupovine.",
            "Izmene odluke biće na snazi do sredine januara i odnose se na ovlašćene menjače i javnog poštanskog operatora.",
            "Izuzetak je predviđen ako su menjači u prethodnih 14 dana prodali građanima najmanje 10 odsto više efektive nego što su otkupili od fizičkih lica.",
            "U tom slučaju rok se produžava na 60 dana, navodi Narodna banka Srbije u odluci objavljenoj u Službenom glasniku.",
        ]
        exception = financial_exception_context(blocks, headline)
        self.assertIn("14 dana", exception)
        self.assertIn("10 odsto", exception)
        extracted = select_news_paragraphs(blocks, headline)
        self.assertTrue(extracted)
        self.assertIn("14 dana", " ".join(extracted))
        self.assertIn("10 odsto", " ".join(extracted))
        self.assertLessEqual(len(extracted), 3)

    def test_financial_exception_not_added_without_source_evidence(self):
        headline = "Menjači dobijaju rok od 60 dana"
        blocks = [
            "NBS je donela odluku o pravilima prodaje efektive bankama u roku od 30 dana.",
            "Novo pravilo odnosi se na ovlašćene menjače i poštanskog operatora.",
        ]
        self.assertEqual(financial_exception_context(blocks, headline), "")

    def test_film_title_from_later_article_paragraph_is_preserved(self):
        headline = ("Kikić pred premijeru dokumentarca o rudarenju u istočnoj Srbiji: "
                    "Kapital stranog investitora ne sme biti prioritet")
        body = [
            "Jelena Kikić, autorka dokumentarca, govorila je o rudarstvu na istoku Srbije, u gradovima Bor i Majdanpek.",
            "U regionu se planiraju nova istraživanja, otvaranje rudnika i moguće preseljenje pojedinih naselja.",
            "Prema njenim rečima, rudarska kompanija radi tokom cele godine, zbog čega su stanovnici zabrinuti.",
            "Film „Kineska četvrt: Rudarska kolonija istok“ govori o životu ljudi u okolini rudnika u istočnoj Srbiji.",
        ]
        context = film_premiere_context(body, headline)
        self.assertIn("Kineska četvrt", context)
        picked = select_news_paragraphs(body, headline)
        self.assertTrue(any("Kineska četvrt" in p for p in picked))
        self.assertLessEqual(len(picked), 3)

    def test_missing_original_film_name_is_not_guessed(self):
        headline = "Kikić pred premijeru dokumentarca o rudarenju u istočnoj Srbiji"
        body = [
            "Jelena Kikić govorila je o rudarenju u Boru i Majdanpeku, ističući probleme meštana.",
            "Novi dokumentarni film govori o širenju rudarskih aktivnosti i mogućem preseljenju sela.",
        ]
        self.assertEqual(film_premiere_context(body, headline), "")

    def test_extraction_avoids_navigation_and_related_articles(self):
        article_html = """<html><body><nav>Newsletter - click here!</nav><article>
          <h1>U Beogradu otvoren novi dom zdravlja</h1>
          <p>U Beogradu je danas otvoren novi dom zdravlja koji će služiti stanovnicima nekoliko opština.</p>
          <p>Grad je saopštio da će ustanova imati dvadeset ordinacija i poseban prostor za dečje preglede.</p>
          <p>Pacijenti će moći da zakažu pregled putem telefona, dok su prvi termini dostupni sledeće nedelje.</p>
          <p>Nova ustanova finansirana je iz gradskog budžeta, a radovi su počeli prošlog leta.</p>
        </article><footer>Related news: Trump and Iran</footer></body></html>"""
        paragraphs = extract_article_paragraphs(article_html)
        self.assertTrue(paragraphs)
        selected = select_news_paragraphs(paragraphs, "U Beogradu otvoren novi dom zdravlja")
        self.assertGreaterEqual(len(selected), 2)
        all_text = " ".join(selected)
        self.assertIn("dvadeset ordinacija", all_text)
        self.assertNotIn("Trump", all_text)
        self.assertNotIn("Newsletter", all_text)

    def test_editorial_facts_question_not_printed(self):
        source = [
            "Grad je objavio nove cene parkiranja koje stupaju na snagu prvog decembra u Beogradu.",
            "Nova tarifa će važiti za prvu i drugu parking zonu, dok će treća zona ostati bez promene.",
            "Koliko će građani plaćati sledeće godine?",
            "Prema saopštenju grada, vozači će novu cenu videti pri plaćanju SMS porukom od ponedeljka.",
        ]
        selected = select_news_paragraphs(source, "Nove cene parkiranja u Beogradu")
        self.assertNotIn("?", " ".join(selected))
        self.assertGreaterEqual(len(selected), 2)

    def test_full_article_required_before_translation(self):
        article = Article("RTS", "Novosti u Beogradu", "https://rts.rs/a", "Kratak pregled", 0)
        class Translator:
            def translate(self, text):
                return "Перевод: " + text
        with patch("bot.fetch_editorial_paragraphs", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Слишком мало"):
                translate_article(article, Translator())

    def test_translation_yields_multiple_paragraphs(self):
        article = Article("RTS", "Novosti u Beogradu", "https://rts.rs/a", "", 0)
        content = [
            "U Beogradu je danas saopšteno da će nova gradska ustanova biti otvorena tokom narednog meseca.",
            "Prema saopštenju gradske uprave, planira se trideset novih radnih mesta i nekoliko ambulanti za decu.",
            "Ministarstvo je navelo da će se završni radovi finansirati sredstvima iz gradskog budžeta za 2026. godinu.",
        ]
        translations = {
            article.title: "В Белграде планируют открыть новое городское учреждение",
            content[0]: "В Белграде сообщили о планах открыть новое городское учреждение в следующем месяце. Оно будет доступно жителям нескольких районов города.",
            content[1]: "По информации городской администрации, для работы учреждения предполагается создать тридцать рабочих мест и оборудовать несколько кабинетов для детей.",
            content[2]: "Министерство уточнило, что завершение строительных работ будет финансироваться из городского бюджета на следующий год. Подготовка помещения уже началась.",
        }
        class Translator:
            def translate(self, text):
                return translations[text]
        with patch("bot.fetch_editorial_paragraphs", return_value=content):
            ru_title, ru_content = translate_article(article, Translator())
        self.assertEqual(ru_content.count("\n\n"), 2)
        self.assertTrue(len(ru_content) > 200)
        self.assertIn("Белграде", ru_title)

    def test_caption_preserves_paragraphs_without_cutting_word(self):
        article = Article("RTS", "Lokalna vest", "https://rts.rs/a", "", 0)
        content = (
            "Первое предложение с основным фактом новости.\n\n"
            "Второй абзац содержит объяснение обстоятельств и несколько важных подробностей.\n\n"
            "Третий абзац посвящён тому, когда изменения начнут действовать."
        )
        caption = photo_caption(article, "Новые изменения в Белграде", content)
        self.assertIn("\n\nВторой абзац", caption)
        self.assertIn("\n\nТретий абзац", caption)
        self.assertIn("Источник: RTS", caption)
        self.assertLessEqual(len(caption.replace("<b>", "").replace("</b>", "")), 1024)

    def test_long_rss_excerpt_remains_concise(self):
        item = Article("RTS", "Novi zakon", "https://rts.rs/a",
                       "Prva rečenica ima važan podatak o Srbiji. "
                       "Druga rečenica objašnjava šta se promenilo. "
                       "Treća rečenica dodaje konkretnu informaciju.",
                       datetime.now(timezone.utc).timestamp())
        excerpt = prepare_summary(item)
        self.assertIn("Druga rečenica", excerpt)
        self.assertLessEqual(len(excerpt), 420)


if __name__ == "__main__":
    unittest.main()
