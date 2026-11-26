"""Regression checks for errors observed in the 26 November 2026 post."""
import unittest
import os
from unittest.mock import patch
import requests

import editorial_quality as eq
import bot
import polish


class EditorialTests(unittest.TestCase):
    def test_specific_falcon_extracted_from_generic_fastest_animal_headline(self):
        title = "World's fastest animal could nearly double its livable territory by 2080"
        summary = "The area suitable for peregrine falcons could grow by 74% in Britain by 2080."
        self.assertEqual(bot.story_topics(title, summary),
                         ("animals", "peregrine falcon"))

    def test_elephant_image_is_rejected_for_falcon_story(self):
        self.assertFalse(eq.photo_matches("peregrine falcon", "File:Elephant Loxodonta africana.jpg"))
        self.assertFalse(eq.photo_matches("wildlife", "File:Elephant calf.jpg"))
        self.assertTrue(eq.photo_matches("peregrine falcon", "File:Falco peregrinus flying.jpg"))

    def test_source_summary_excerpt_does_not_end_mid_sentence(self):
        source = ("A new study suggests the habitat of peregrine falcons "
                  "could expand by 74% in a high-emissions scenario. "
                  "A second incomplete sentence about a high")
        summary = eq.english_excerpt(source)
        self.assertTrue(summary.endswith("scenario."))
        self.assertNotIn("incomplete", summary)

    def test_caption_never_cuts_long_word_or_sentence(self):
        footer = '🔗 <a href="https://example.org">Источник</a>'
        title = "Сапсаны могут расширить свой ареал в Великобритании"
        summary = ("К 2080 году территория, пригодная для обитания сапсанов, "
                   "может увеличиться на 74%. " + "Очень " * 160 +
                   "исследователи делают ещё один вывод.")
        caption = eq.compose_caption(title, summary, footer, "🐦")
        self.assertTrue(caption.endswith(footer))
        self.assertIn("74%.", caption)
        self.assertNotIn("делают ещё один вывод", caption)

    def test_oversized_headline_is_rejected_not_clipped(self):
        title = "Самое быстрое животное в мире может почти удвоить свою пригодную для жизни территорию к 2080 году в Великобритании из-за изменения климата"
        result = eq.compose_caption(title,
             "Сапсаны могут расширить свой ареал на 74% к 2080 году.",
             "🔗 Источник", "🐦")
        self.assertEqual(result, "")

    def test_incomplete_translation_is_rejected(self):
        result = eq.compose_caption("Сапсаны и климат",
            "Территория может увеличиться на 74% в случае климатического сценария с высоким уровнем",
            "🔗 Источник", "🐦")
        self.assertEqual(result, "")

    def test_ai_editor_keeps_falcon_uncertainty_and_numbers(self):
        src_title = "Peregrine falcons could see habitat grow 74% by 2080"
        src_summary = "The area suitable for peregrine falcons could grow by 74% in 2080."
        self.assertTrue(polish.editorial_ok(
            src_title, src_summary,
            "Сапсаны могут расширить ареал на 74% к 2080 году",
            "В Великобритании территория для сапсанов может увеличиться на 74% к 2080 году."
        ))

    def test_ai_editor_rejects_invented_numbers(self):
        self.assertFalse(polish.editorial_ok(
            "Peregrine falcons could gain 74% habitat by 2080",
            "The area suitable for peregrine falcons could grow by 74% by 2080.",
            "Сапсаны могут расширить ареал на 90% к 2080 году",
            "Учёные прогнозируют рост площади на 90% к 2080 году."
        ))

    def test_ai_editor_rejects_certainty_and_missing_species(self):
        self.assertFalse(polish.editorial_ok(
            "Peregrine falcons could gain habitat",
            "The area suitable for peregrine falcons could expand in future.",
            "Самое быстрое животное гарантированно получит новые земли",
            "Его среда обитания точно увеличится."
        ))

    def test_editor_falls_back_when_groq_unreachable(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            with patch.object(polish.requests, "post", side_effect=requests.Timeout):
                output = polish.polish(
                    "Peregrine falcons may gain habitat",
                    "Peregrine falcons may gain habitat in Britain.",
                    "Сапсаны могут расширить ареал",
                    "Площадь их потенциальной среды обитания может увеличиться."
                )
        self.assertEqual(output, (
            "Сапсаны могут расширить ареал",
            "Площадь их потенциальной среды обитания может увеличиться."
        ))

    def test_verified_falcon_fallback_is_species_specific(self):
        self.assertIsNone(bot.verified_species_fallback("wildlife", {"posted": {}}))
        self.assertIsNone(bot.verified_species_fallback("elephant", {"posted": {}}))
        class FakePhoto:
            status_code = 200
            headers = {"content-type": "image/jpeg"}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def raise_for_status(self): pass
            def iter_content(self, n): yield b"\xff\xd8" + b"data"
        with patch.object(bot.HTTP, "get", return_value=FakePhoto()):
            image = bot.verified_species_fallback("peregrine falcon", {"posted": {}})
        self.assertIsNotNone(image)
        self.assertIn("Falco_peregrinus.jpg", image["url"])

    def test_caption_is_valid_and_fits_telegram(self):
        caption = eq.compose_caption("Изменение климата может расширить ареал сапсанов",
            "Учёные прогнозируют увеличение подходящей для сапсанов территории в Великобритании на 74% к 2080 году. "
            "Но это не гарантирует соответствующего роста популяции.",
            '🔗 <a href="https://phys.org/">Источник</a> · <a href="https://commons.wikimedia.org/">Иллюстрация</a>', "🐦")
        self.assertTrue(caption)
        self.assertLessEqual(len(caption), 1024)
        self.assertTrue(caption.endswith('Иллюстрация</a>'))


if __name__ == "__main__":
    unittest.main()
