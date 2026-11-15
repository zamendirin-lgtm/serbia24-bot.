import json
import os
import unittest
from unittest.mock import patch

from editorial import (
    SYSTEM_RULES, EditedNews, EditorialError,
    conservative_polish, edit_news, edit_with_gemini, edit_with_groq, _numbers, _clean,
    ensure_conditional_rules_explained, MissingConditionError, _basic_checks,
    ensure_cultural_award_is_explained, UnexplainedTermError,
    review_with_groq,
)

TITLE = "В Нови-Саде открыли новый медицинский центр"
PARA1 = ("В Нови-Саде открылся новый медицинский центр для жителей трёх районов. "
         "Учреждение начало принимать пациентов в четверг.")
PARA2 = ("В центре работают врачи общей практики и педиатры. "
         "Записаться на приём можно по телефону или в регистратуре.")
PARA3 = ("Городская администрация сообщает, что работы завершились по графику. "
         "Дополнительные кабинеты планируется открыть позднее.")
SERBIAN = [
    "U Novom Sadu otvoren je novi dom zdravlja koji je počeo da prima pacijente u četvrtak.",
    "U centru rade lekari opšte prakse i pedijatri, a pregledi se zakazuju telefonom.",
    "Gradska uprava navela je da su radovi završeni prema planu.",
]


class EditorialTests(unittest.TestCase):
    def test_no_key_deterministic_cleaning(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            edited = edit_news("Novi centar", SERBIAN, TITLE,
                               "— " + PARA1 + "\n\n– " + PARA2)
        self.assertEqual(edited.mode, "without_ai")
        self.assertEqual(edited.paragraphs[0], PARA1)
        self.assertEqual(edited.paragraphs[1], PARA2)

    def test_repeated_paragraph_rejected(self):
        with self.assertRaises(EditorialError):
            conservative_polish(TITLE, PARA1 + "\n\n" + PARA1)

    def test_no_additional_numbers_permitted(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"candidates": [{"content": {"parts": [
                    {"text": json.dumps({
                        "publish": True,
                        "title": TITLE,
                        "paragraphs": [PARA1 + " Стоимость составила 900 динаров.", PARA2],
                    }, ensure_ascii=False)}
                ]}}]}
        with patch("editorial.requests.post", return_value=Response()):
            with self.assertRaisesRegex(EditorialError, "цифры"):
                edit_with_gemini("Novi centar", SERBIAN, TITLE,
                                 PARA1 + "\n\n" + PARA2, api_key="test-secret")

    def test_gemini_editor_returns_substantive_post(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"candidates": [{"content": {"parts": [
                    {"text": json.dumps({
                        "publish": True,
                        "title": TITLE,
                        "paragraphs": [PARA1, PARA2],
                    }, ensure_ascii=False)}
                ]}}]}
        with patch("editorial.requests.post", return_value=Response()) as post:
            edited = edit_with_gemini("Novi centar", SERBIAN, TITLE,
                                      PARA1 + "\n\n" + PARA2, api_key="test-secret")
        self.assertEqual(edited.mode, "ai")
        self.assertIn("Нови-Саде", edited.text)
        self.assertIn("generativelanguage.googleapis.com", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-secret")
        self.assertIn("Не сочиняй", SYSTEM_RULES)

    def test_gemini_declines_unclear_story(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"candidates": [{"content": {"parts": [
                    {"text": '{"publish": false, "title": "", "paragraphs": []}'}
                ]}}]}
        with patch("editorial.requests.post", return_value=Response()):
            with self.assertRaisesRegex(EditorialError, "отклонил"):
                edit_with_gemini("Novi centar", SERBIAN, TITLE,
                                 PARA1 + "\n\n" + PARA2, api_key="test-secret")

    def test_gemini_refuses_unexpected_model_path(self):
        with self.assertRaisesRegex(EditorialError, "модель"):
            edit_with_gemini("Novi centar", SERBIAN, TITLE,
                             PARA1 + "\n\n" + PARA2,
                             api_key="test-secret", model="../../wrong")


    def test_hours_normalization_no_fabricated_time(self):
        self.assertEqual(_numbers("В 19:00"), {"19"})
        self.assertEqual(_numbers("В 19 часов"), {"19"})
        self.assertEqual(_numbers("В 19:30"), {"19", "30"})
        self.assertNotEqual(_numbers("В 19 часов"), _numbers("В 19:30"))

    def test_machine_translation_phrasing_normalized(self):
        self.assertIn("мастер-класс", _clean("Сегодня workshop по концентрации."))
        self.assertIn("мероприятий", _clean("Организует серию активностей."))
        self.assertIn("для молодёжи", _clean("Мероприятие для молодых."))
        self.assertIn("Молодёжным клубом", _clean("организовано ОМЛАДЕНЧЕСКИМ КЛУБОМ SKC."))

    def test_singular_news_event_verb_agreement(self):
        corrected = _clean("В Крагуеваце вечером пройдут мастер‑класс о внимании.")
        self.assertIn("пройдёт мастер‑класс", corrected)
        self.assertNotIn("пройдут мастер", corrected)

    def test_second_ai_reader_review_improves_awkward_news(self):
        article = "Nove izmene zakona"
        initial = EditedNews(TITLE, (PARA1, PARA2), "groq")
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "approved": True,
                    "title": "В Нови-Саде открыли медицинский центр: кто может записаться",
                    "paragraphs": [PARA1, PARA2],
                }, ensure_ascii=False)}}]}
        with patch("editorial.requests.post", return_value=Response()) as post:
            reviewed = review_with_groq(
                article, SERBIAN, initial, api_key="test-groq",
            )
        self.assertEqual(reviewed.mode, "groq+review")
        self.assertIn("Нови-Саде", reviewed.title)
        self.assertEqual(len(reviewed.paragraphs), 2)
        instructions = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("пожизненная", instructions)
        self.assertIn("обычных жителей", instructions)

    def test_second_ai_reader_rejection_blocks_news(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {
                    "content": '{"approved":false,"title":"","paragraphs":[]}'
                }}]}
        with patch("editorial.requests.post", return_value=Response()):
            with self.assertRaisesRegex(EditorialError, "отклонил"):
                review_with_groq(
                    "Novi centar", SERBIAN,
                    EditedNews(TITLE, (PARA1, PARA2), "groq"),
                    api_key="test-groq",
                )

    def test_second_ai_reader_is_called_when_enabled(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "groq-test", "GEMINI_API_KEY": "",
            "EDITOR_REVIEW_ENABLED": "1",
        }), patch("editorial.edit_with_groq",
                 return_value=EditedNews(TITLE, (PARA1, PARA2), "groq")) as first, \
             patch("editorial.review_with_groq",
                   return_value=EditedNews(TITLE, (PARA1, PARA2), "groq+review")) as second:
            reviewed = edit_news("Novi centar", SERBIAN, TITLE,
                                 PARA1 + "\n\n" + PARA2)
        self.assertEqual(reviewed.mode, "groq+review")
        first.assert_called_once()
        second.assert_called_once()

    def test_second_ai_reader_cannot_invent_money(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "approved": True, "title": TITLE,
                    "paragraphs": [PARA1 + " Стоимость 8888 динаров.", PARA2],
                }, ensure_ascii=False)}}]}
        with patch("editorial.requests.post", return_value=Response()):
            with self.assertRaisesRegex(EditorialError, "цифры"):
                review_with_groq(
                    "Novi centar", SERBIAN,
                    EditedNews(TITLE, (PARA1, PARA2), "groq"),
                    api_key="test-groq",
                )

    def test_national_arts_pensions_must_be_defined_for_readers(self):
        source = (
            "Ministar kulture Selaković dobio dodatna ovlašćenja za "
            "nacionalne penzije. Udruženje dramskih umetnika Srbije ponovo "
            "predložilo Bošković, Savina i Kovačevića."
        )
        vague = [
            "Ministar kulture Nikola Selaković dobio je proširena ovlašćenja da predlaže vladi nove kandidate za nacionalne penzije.",
            "Udruženje dramskih umetnika Srbije ponovo je kandidovalo tri predstavnika čiji su raniji zahtevi odbijeni.",
        ]
        with self.assertRaisesRegex(UnexplainedTermError, "пожизненная"):
            ensure_cultural_award_is_explained(
                "Селакович получил больше прав для национальных пенсий",
                vague, source,
            )

    def test_clear_national_arts_pension_passes(self):
        source = (
            "Selakoviću proširena ovlašćenja za nacionalne penzije: "
            "ministar ima pravo da predloži dodatne kandidate umetnika."
        )
        paragraphs = [
            "Национальная пенсия в Сербии — пожизненная ежемесячная денежная выплата за выдающийся вклад в культуру. Министр может выдвигать кандидатов.",
            "Ассоциация драматических артистов потребовала дождаться формирования нового правительства, чтобы решение было принято профессиональной комиссией.",
        ]
        ensure_cultural_award_is_explained(
            "В Сербии изменили порядок национальных пенсий для артистов",
            paragraphs, source,
        )

    def test_national_pension_expansion_must_state_old_and_new_limit(self):
        source = (
            "U septembru je izmenjen propis o nacionalnim penzijama, "
            "ministar može samostalno da predloži od pet na deset kandidata."
        )
        vague = [
            "Министр культуры получил расширенные полномочия в сфере национальных пенсий. Это пожизненные ежемесячные денежные выплаты за заслуги в культуре.",
            "По новым правилам министр может выдвигать до 10 кандидатов на получение государственной награды, но прежнее ограничение не упоминается.",
        ]
        with self.assertRaisesRegex(UnexplainedTermError, "5 кандидатов"):
            ensure_cultural_award_is_explained(
                "Министр культуры предложит до 10 кандидатов на национальные пенсии",
                vague, source,
            )
        corrected = [
            "В Сербии расширили полномочия министра культуры. Он может предложить до 10 кандидатов вместо прежних 5 на пожизненную ежемесячную денежную выплату за вклад в культуру.",
            "Ассоциация драматических артистов требует отложить решение до формирования нового правительства и независимой профессиональной комиссии.",
        ]
        ensure_cultural_award_is_explained(
            "Изменили правила национальных пенсий для артистов",
            corrected, source,
        )

    def test_cultural_award_accepts_before_after_numbers_written_as_words(self):
        source = (
            "Ministar kulture Selaković dobio pravo na nacionalne penzije "
            "sa pet na deset kandidata."
        )
        title = "Министр культуры сможет предложить вдвое больше кандидатов"
        paragraphs = [
            "Национальная пенсия в Сербии — пожизненная ежемесячная денежная выплата за выдающийся вклад в культуру. Министр культуры получил дополнительные полномочия.",
            "Теперь министр может предложить правительству до десяти кандидатов вместо прежних пяти, помимо заявок профессиональных творческих объединений.",
        ]
        ensure_cultural_award_is_explained(title, paragraphs, source)

    def test_normal_retirement_pension_not_treated_as_arts_award(self):
        ensure_cultural_award_is_explained(
            "Пенсии в Сербии проиндексируют в декабре",
            [
                "Правительство Сербии увеличит выплаты пенсионерам по возрасту.",
                "Повышение затронет получателей обычных страховых пенсий.",
            ],
            "Penzije u Srbiji biće uvećane u decembru.",
        )

    def test_nbs_60_vs_30_day_omitted_exception_rejected(self):
        source = (
            "NBS omogućila ovlašćenim menjačima prodaju efektive bankama do 60 dana. "
            "Obično važi rok 30 dana, a izuzetno 60 dana ako su u prethodnih "
            "14 dana prodali građanima najmanje 10 odsto više efektive nego što su otkupili."
        )
        headline = "НБС разрешил обменникам продавать валюту банкам до 60 дней"
        incomplete = [
            "Национальный банк Сербии изменил правила валютных операций: почта и обменники теперь могут продавать купленную валюту банкам в течение 60 дней.",
            "Согласно новым положениям, лицензированные обменные пункты должны возвращать валюту банкам не позднее 30 дней после её приобретения у банка.",
        ]
        with self.assertRaises(MissingConditionError):
            ensure_conditional_rules_explained(headline, incomplete, source)

    def test_nbs_conditional_60_day_exception_must_include_14_days_10_percent(self):
        source = (
            "NBS: uobičajen rok je 30 dana, izuzetno do 60 dana, ako su "
            "u prethodnih 14 dana prodali građanima najmanje 10 odsto više "
            "valute nego što su otkupili od građana."
        )
        headline = "Нацбанк Сербии изменил сроки для обменников: 30 или 60 дней"
        vague = [
            "Лицензированные обменники должны возвращать ранее приобретённую у банков валюту в течение 30 дней после её покупки.",
            "В отдельных случаях этот срок увеличивается до 60 дней при выполнении установленных условий, говорится в решении регулятора.",
        ]
        with self.assertRaisesRegex(MissingConditionError, "14 дней"):
            ensure_conditional_rules_explained(headline, vague, source)

    def test_nbs_explained_30_day_and_60_day_rules_accepted(self):
        source = (
            "NBS dozvoljava pošti i menjačima rok 30 dana; u posebnim "
            "slučajevima 60 dana. Ako su za prethodnih 14 dana prodali građanima "
            "najmanje 10 odsto više valute nego što su otkupili."
        )
        headline = "Обменникам в Сербии разрешили возвращать валюту позже"
        good = [
            "Нацбанк Сербии разрешил обменникам возвращать купленную у банков валюту в течение 30 дней. Условия касаются операций обменников с банками, а не обмена валюты между гражданами.",
            "Срок увеличивается до 60 дней только при условии, что за предыдущие 14 дней обменник продал населению как минимум на 10% больше валюты, чем купил у клиентов.",
        ]
        ensure_conditional_rules_explained(headline, good, source)

    def test_nbs_single_deadline_unchanged(self):
        source = "NBS: za ovlašćene menjače rok za vraćanje efektive bankama je 30 dana."
        ensure_conditional_rules_explained(
            "Новые правила обмена валюты", [
                "Нацбанк продлил срок возврата валюты банкам до 30 дней.",
                "Это правило касается лицензированных обменных пунктов.",
            ], source,
        )

    def test_groq_retries_when_financial_exception_not_explained(self):
        source_title = "NBS: redovno 30 dana, izuzetno 60 dana za menjače"
        source_paras = [
            "Menjači vraćaju bankama efektivu u roku od 30 dana.",
            "Izuzetno važi rok od 60 dana ako su u prethodnih 14 dana "
            "prodali građanima najmanje 10 odsto više valute nego što su otkupili.",
        ]
        headline = "Нацбанк изменил сроки для обменников"
        bad = {
            "publish": True, "title": headline,
            "paragraphs": [
                "Нацбанк разрешил лицензированным обменным пунктам возвращать валюту банкам в срок до 60 дней, сообщается в новом решении регулятора.",
                "При этом действующие правила также предусматривают возврат валюты банкам в течение 30 дней с момента её покупки у них.",
            ],
        }
        good = {
            "publish": True, "title": headline,
            "paragraphs": [
                "Обычно обменные пункты Сербии должны вернуть банкам купленную у них валюту в течение 30 дней. Это правило регулирует операции самих обменников.",
                "Срок можно увеличить до 60 дней только если за предыдущие 14 дней обменник продал клиентам валюты минимум на 10% больше, чем купил у них.",
            ],
        }
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {
                    "content": json.dumps(self.payload, ensure_ascii=False),
                }}]}
        with patch("editorial.requests.post", side_effect=[
            Response(bad), Response(good),
        ]) as requests_post:
            item = edit_with_groq(
                source_title, source_paras, headline,
                "Обычный срок 30 дней.\n\nИногда срок до 60 дней.",
                api_key="placeholder",
            )
        self.assertEqual(item.mode, "groq")
        self.assertIn("14 дней", item.text)
        self.assertIn("10%", item.text)
        self.assertEqual(requests_post.call_count, 2)

    def test_groq_api_uses_free_model_and_json(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "publish": True,
                    "title": TITLE,
                    "paragraphs": [PARA1, PARA2]
                }, ensure_ascii=False)}}]}
        with patch("editorial.requests.post", return_value=Response()) as post:
            item = edit_with_groq("Novi centar", SERBIAN, TITLE,
                                  PARA1 + "\n\n" + PARA2,
                                  api_key="fake-secret")
        self.assertEqual(item.mode, "groq")
        self.assertEqual(len(item.paragraphs), 2)
        request = post.call_args.kwargs
        self.assertEqual(request["json"]["model"], "openai/gpt-oss-120b")
        self.assertEqual(request["json"]["response_format"], {"type": "json_object"})
        self.assertIn("Bearer fake-secret", request["headers"]["Authorization"])
        self.assertIn("интригующий", request["json"]["messages"][0]["content"])
        self.assertIn("ПЕРВОМ абзаце", request["json"]["messages"][0]["content"])

    def test_groq_unsubstantiated_numbers_rejected(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "publish": True, "title": TITLE,
                    "paragraphs": [PARA1 + " Потрачено 9999 евро.", PARA2]
                }, ensure_ascii=False)}}]}
        with patch("editorial.requests.post", return_value=Response()):
            with self.assertRaisesRegex(EditorialError, "цифры"):
                edit_with_groq("Novi centar", SERBIAN, TITLE,
                               PARA1 + "\n\n" + PARA2, api_key="fake-secret")

    def test_groq_retries_serbian_and_accepts_russian_second_response(self):
        serbian = {
            "publish": True,
            "title": "Заступника удружења грађана ухапсила полиција у Новом Саду",
            "paragraphs": [
                "По налогу Вишег јавног тужилаштва у Новом Саду, полиција је ухапсила представника удружења грађана због сумње да је злоупотребио положај.",
                "Тужилаштво је саопштило да се осумњичени терети за злоупотребу положаја одговорног лица, а да је полиција предузела потребне мере.",
            ],
        }
        russian = {"publish": True, "title": TITLE, "paragraphs": [PARA1, PARA2]}

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {
                    "content": json.dumps(self.payload, ensure_ascii=False)
                }}]}

        with patch("editorial.requests.post", side_effect=[
                Response(serbian), Response(russian)]) as post:
            item = edit_with_groq("Novi centar", SERBIAN, TITLE,
                                  PARA1 + "\n\n" + PARA2, api_key="fake-secret")
        self.assertEqual(item.mode, "groq")
        self.assertEqual(item.title, TITLE)
        self.assertEqual(post.call_count, 2)
        self.assertIn(
            "КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ ПРЕДЫДУЩЕЙ ВЕРСИИ",
            post.call_args_list[1].kwargs["json"]["messages"][0]["content"],
        )

    def test_groq_two_serbian_outputs_are_never_accepted(self):
        bad = {
            "publish": True,
            "title": "Заступника удружења грађана ухапсила полиција у Новом Саду",
            "paragraphs": [
                "По налогу Вишег јавног тужилаштва у Новом Саду, полиција је ухапсила представника удружења грађана због сумње да је злоупотребио положај.",
                "Тужилаштво је саопштило да се осумњичени терети за злоупотребу положаја одговорног лица, а да је полиција предузела потребне мере.",
            ],
        }
        class Response:
            def raise_for_status(self): return None
            def json(self):
                return {"choices": [{"message": {
                    "content": json.dumps(bad, ensure_ascii=False)
                }}]}
        with patch("editorial.requests.post", return_value=Response()) as post:
            with self.assertRaisesRegex(EditorialError, "дважды вернул"):
                edit_with_groq("Novi centar", SERBIAN, TITLE,
                               PARA1 + "\n\n" + PARA2, api_key="fake-secret")
        self.assertEqual(post.call_count, 2)

    def test_groq_prioritized_over_gemini(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "groq-test", "GEMINI_API_KEY": "gemini-test"}), \
             patch("editorial.edit_with_groq", return_value=EditedNews(TITLE, (PARA1, PARA2), "groq")) as groq, \
             patch("editorial.edit_with_gemini") as gemini:
            item = edit_news("Novi centar", SERBIAN, TITLE,
                             PARA1 + "\n\n" + PARA2)
        self.assertEqual(item.mode, "groq")
        groq.assert_called_once()
        gemini.assert_not_called()

    def test_gemini_fallback_when_groq_unavailable(self):
        def fails(*args, **kwargs):
            raise EditorialError("Не удалось проверить новость через Groq")
        with patch.dict(os.environ, {
                "GROQ_API_KEY": "groq-test", "GEMINI_API_KEY": "gemini-test",
                "GOOGLE_API_KEY": ""}), \
             patch("editorial.edit_with_groq", side_effect=fails) as groq, \
             patch("editorial.edit_with_gemini",
                   return_value=EditedNews(TITLE, (PARA1, PARA2), "ai")) as gemini:
            item = edit_news("Novi centar", SERBIAN, TITLE,
                             PARA1 + "\n\n" + PARA2)
        self.assertEqual(item.mode, "ai")
        groq.assert_called_once()
        gemini.assert_called_once()

    def test_gemini_works_with_google_api_key_secret_alias(self):
        with patch.dict(os.environ, {
                "GROQ_API_KEY": "", "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "google-test"}), \
             patch("editorial.edit_with_gemini",
                   return_value=EditedNews(TITLE, (PARA1, PARA2), "ai")) as gemini:
            item = edit_news("Novi centar", SERBIAN, TITLE,
                             PARA1 + "\n\n" + PARA2)
        self.assertEqual(item.mode, "ai")
        gemini.assert_called_once()

    def test_explicit_groq_refusal_not_overridden(self):
        with patch.dict(os.environ, {
                "GROQ_API_KEY": "groq-test", "GEMINI_API_KEY": "gemini-test"}), \
             patch("editorial.edit_with_groq",
                   side_effect=EditorialError("Groq-редактор отклонил недостаточно содержательную новость")), \
             patch("editorial.edit_with_gemini") as gemini:
            with self.assertRaises(EditorialError):
                edit_news("Novi centar", SERBIAN, TITLE,
                          PARA1 + "\n\n" + PARA2)
            gemini.assert_not_called()

    def test_model_denial_skips_publication(self):
        with self.assertRaisesRegex(EditorialError, "Неизвестная модель"):
            edit_with_groq("Novi centar", SERBIAN, TITLE,
                           PARA1 + "\n\n" + PARA2,
                           api_key="fake-secret", model="../../other")



if __name__ == "__main__":
    unittest.main()
