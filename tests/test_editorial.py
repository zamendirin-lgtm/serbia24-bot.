import json
import os
import unittest
from unittest.mock import patch

from editorial import (
    SYSTEM_RULES, EditedNews, EditorialError,
    conservative_polish, edit_news, edit_with_gemini, edit_with_groq,
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

    def test_groq_prioritized_over_gemini(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "groq-test", "GEMINI_API_KEY": "gemini-test"}), \
             patch("editorial.edit_with_groq", return_value=EditedNews(TITLE, (PARA1, PARA2), "groq")) as groq, \
             patch("editorial.edit_with_gemini") as gemini:
            item = edit_news("Novi centar", SERBIAN, TITLE,
                             PARA1 + "\n\n" + PARA2)
        self.assertEqual(item.mode, "groq")
        groq.assert_called_once()
        gemini.assert_not_called()

    def test_model_denial_skips_publication(self):
        with self.assertRaisesRegex(EditorialError, "Неизвестная модель"):
            edit_with_groq("Novi centar", SERBIAN, TITLE,
                           PARA1 + "\n\n" + PARA2,
                           api_key="fake-secret", model="../../other")



if __name__ == "__main__":
    unittest.main()
