import unittest

from language_guard import ensure_russian, WrongLanguageError

RUSSIAN_TITLE = "Полиция Нови-Сада задержала представителя общественной организации"
RUSSIAN_BODY = [
    "По распоряжению прокуратуры полиция задержала представителя общественной организации по подозрению в злоупотреблении служебным положением.",
    "Следствие считает, что городскому бюджету мог быть причинён ущерб примерно в два миллиона динаров. Обстоятельства расходования бюджетных средств проверяются.",
]

# Regression from an actual screenshot of Serbia24: Serbian Cyrillic disguised
# as a Russian post. It must never reach the Telegram publish function.
SERBIAN_TITLE = "Заступника удружења грађана И. Б. ухапсила полиција у Новом Саду"
SERBIAN_BODY = [
    "По налогу Вишег јавног тужилаштва у Новом Саду, полиција је ухапсила И. Б., заступника удружења грађана, због сумње да је злоупотребом свог положаја оштетио буџет града за 2,7 милиона динара.",
    "Тумачи се да су од 2021. године удружењу грађана додељена средства града, а тужилаштво га оптужује за кривично дело злоупотребе положаја одговорног лица.",
]

class RussianGuardTests(unittest.TestCase):
    def test_acceptable_russian_news(self):
        ensure_russian(RUSSIAN_TITLE, RUSSIAN_BODY)

    def test_serbian_cyrillic_in_both_title_and_body_rejected(self):
        with self.assertRaises(WrongLanguageError):
            ensure_russian(SERBIAN_TITLE, SERBIAN_BODY)

    def test_serbian_cyrillic_only_in_body_rejected(self):
        with self.assertRaises(WrongLanguageError):
            ensure_russian(RUSSIAN_TITLE, [SERBIAN_BODY[0], RUSSIAN_BODY[1]])

    def test_serbian_cyrillic_only_in_title_rejected(self):
        with self.assertRaises(WrongLanguageError):
            ensure_russian(SERBIAN_TITLE, RUSSIAN_BODY)

    def test_serbian_latin_paragraph_rejected(self):
        with self.assertRaises(WrongLanguageError):
            ensure_russian(RUSSIAN_TITLE, [
                "Po nalogu višeg javnog tužilaštva u Novom Sadu, policija je uhapsila zastupnika udruženja građana zbog sumnje u zloupotrebu položaja.",
                RUSSIAN_BODY[1],
            ])

    def test_short_russian_headline_not_false_positive(self):
        ensure_russian("Новые меры в Белграде", RUSSIAN_BODY)

    def test_serbian_without_special_serbian_letters_rejected(self):
        with self.assertRaises(WrongLanguageError):
            ensure_russian("Нови Сад: нови закон", [
                "Влада Србије донела је нови закон који се односи на радове у центру града и нове трошкове из јавног буџета.",
                "Данас су представници града саопштили да су претходни планови одобрени и да ће радови бити завршени наредне године.",
            ])


if __name__ == "__main__":
    unittest.main()
