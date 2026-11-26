"""Regression checks for errors observed in the 26 November 2026 post."""
import unittest

import editorial_quality as eq
import bot


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
