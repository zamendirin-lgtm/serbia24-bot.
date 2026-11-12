import unittest

from context_guard import (
    MissingContextError, ensure_resolved_context, missing_film_identity,
)

HEADING = "Кикич: В Восточной Сербии добыча руды не должна быть важнее интересов жителей"
VAGUE = [
    "Кикич, глава местного совета, заявила перед премьерой документального фильма, что добыча полезных ископаемых в Восточной Сербии затрагивает интересы местных жителей.",
    "По её словам, китайский инвестор ведёт работы в регионе, а население опасается расширения шахт и возможного переселения целых населённых пунктов.",
]
COMPLETE = [
    "Журналистка Елена Кикич представила документальный фильм «Китайский квартал: Горнодобывающая колония — Восток». Показ состоится 14 ноября в 20:30 на TV Nova.",
    "Фильм рассказывает о жителях Бора, Майданпека и окрестностей Заечара, где расширение горнодобывающих работ вызывает опасения за будущее населённых пунктов.",
]

class ContextGuardTests(unittest.TestCase):
    def test_unidentified_film_in_real_serbia24_style_rejected(self):
        self.assertTrue(missing_film_identity(HEADING, VAGUE))
        with self.assertRaises(MissingContextError):
            ensure_resolved_context(HEADING, VAGUE)

    def test_named_documentary_is_accepted(self):
        self.assertFalse(missing_film_identity(HEADING, COMPLETE))
        ensure_resolved_context(HEADING, COMPLETE)

    def test_non_film_news_not_affected(self):
        title = "В Белграде изменились тарифы на коммунальные услуги"
        body = [
            "Городская администрация сообщила о повышении тарифов, которое затронет счета жителей.",
            "Новые суммы и даты введения тарифов опубликованы на официальном сайте администрации.",
        ]
        self.assertFalse(missing_film_identity(title, body))

    def test_generic_premiere_without_film_identity_is_rejected(self):
        title = "Премьера документального фильма о рудниках состоится в Сербии"
        body = [
            "Авторы документального фильма рассказали о жизни в Восточной Сербии.",
            "После просмотра авторы планируют ответить на вопросы жителей.",
        ]
        self.assertTrue(missing_film_identity(title, body))


if __name__ == "__main__":
    unittest.main()
