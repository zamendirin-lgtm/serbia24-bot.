import unittest
from reader_quality import (
    QualityRejected, validate_grade, unidiomatic_phrases,
    source_grounded_status_guard,
)

SCORES_10 = {
    "clarity": 2, "completeness": 2, "russian": 2,
    "headline": 2, "fidelity": 2
}


class ReaderQualityTests(unittest.TestCase):
    def good(self, **overrides):
        scores = {**SCORES_10, **overrides}
        return {"scores": scores, "critical_issues": []}

    def test_eight_is_accepted_if_no_critical_errors(self):
        grade = validate_grade(self.good(clarity=1, headline=1),
            "В Белграде изменили тарифы на проезд",
            ["Городские власти изменили тарифы на общественный транспорт.",
             "Новые правила вступят в силу после официальной публикации."])
        self.assertEqual(grade.total, 8)

    def test_seven_of_ten_rejected(self):
        with self.assertRaisesRegex(QualityRejected, "7/10"):
            validate_grade(self.good(clarity=1, completeness=1, headline=1),
                "Новость", ["Текст первого абзаца.", "Текст второго абзаца."])

    def test_fidelity_must_have_two_even_at_nine(self):
        with self.assertRaisesRegex(QualityRejected, "точность"):
            validate_grade(self.good(fidelity=1),
                "Новость", ["Первый абзац.", "Второй абзац."])

    def test_fatal_error_rejected_despite_ten(self):
        review = self.good()
        review["critical_issues"] = ["wrong_status"]
        with self.assertRaisesRegex(QualityRejected, "wrong_status"):
            validate_grade(review, "Новость", ["Первый", "Второй"])

    def test_bad_language_cliches_blocked(self):
        problems = unidiomatic_phrases(
            "Парламент был проточным котлом для законов",
            ["Политолог сказал, что парламент работал как проточный бойлер.",
             "Он рассчитывает на изменения после выборов."])
        self.assertTrue(problems)
        with self.assertRaisesRegex(QualityRejected, "Механический перевод"):
            validate_grade(self.good(),
                "Парламент был проточным котлом для законов",
                ["Политолог сказал, что парламент работал как проточный бойлер.",
                 "Он рассчитывает на изменения после выборов."])

    def test_possible_inspector_transfer_not_claimed_as_done(self):
        source = (
            "Komunalni inspektor Vladislav Bosić pozvan je na proveru "
            "kompetencija za eventualni premeštaj u poresku upravu."
        )
        with self.assertRaisesRegex(QualityRejected, "состоявшийся перевод"):
            source_grounded_status_guard(source,
                "Инспектора уже перевели в налоговую службу",
                ["Его перевод состоялся несмотря на возражения.",
                 "Организация инспекторов выразила обеспокоенность."])

    def test_proposed_inspector_transfer_stays_proposed(self):
        source = (
            "Komunalni inspektor Bosić pozvan je na proveru "
            "kompetencija za mogući premeštaj u poresku upravu."
        )
        source_grounded_status_guard(source,
            "Инспектора могут перевести в налоговую службу",
            ["Для возможного перевода назначили проверку знаний.",
             "Общественная организация опасается давления на инспектора."])

    def test_missing_quality_does_not_default_to_ten(self):
        with self.assertRaisesRegex(QualityRejected, "Нет редакторской"):
            validate_grade(None, "Заголовок", ["Текст", "Текст"])
        with self.assertRaisesRegex(QualityRejected, "пять критериев"):
            validate_grade({"scores": {"clarity": 2}, "critical_issues": []},
                           "Заголовок", ["Текст", "Текст"])

if __name__ == "__main__":
    unittest.main()
