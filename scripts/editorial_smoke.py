"""Test actual Russian news rewrite without Telegram publishing.

All editorial tests here use a clearly fictional demonstration brief.
Never print secrets, raw API error responses, or request headers.
"""
from __future__ import annotations
import os
from unittest.mock import patch
import editorial
from editorial import edit_with_groq, edit_with_gemini, EditorialError

SOURCE_TITLE = "U Kragujevcu večeras radionica o koncentraciji u doba digitalnih distrakcija"
SOURCE_PARAS = [
    "Večeras u 19 časova u prostoru Kutija šibica Studentskog kulturnog centra Kragujevac biće održana radionica Koncentracija u doba digitalnih distrakcija.",
    "Radionicu organizuje Omladinski klub SKC, koji tokom novembra priređuje aktivnosti za mlade usmerene na učenje i razvoj ličnih i socijalnih veština.",
    "Organizatori ističu da žele da stvore prostor za druženje, razmenu iskustava i razgovor o svakodnevnim izazovima za mlade.",
]
TITLE_RU = "В Крагуеваце состоится занятие о концентрации в эпоху цифровых отвлечений"
DRAFT_RU = (
    "Вечером в 19 часов в пространстве «Спичечная коробка» Студенческого культурного центра Крагуеваца пройдет занятие о концентрации в эпоху цифровых отвлечений.\n\n"
    "Встречу организует Молодёжный клуб SKC, который в ноябре проводит мероприятия для молодых людей, направленные на обучение, обмен опытом и развитие личных и социальных навыков. Организаторы хотят создать пространство для общения и обсуждения повседневных трудностей."
)

def check(label, api_key, call):
    if not api_key:
        print(label + ": no key")
        return False
    original_check = editorial._basic_checks
    def debug_check(title, paragraphs, factual_input):
        # This is a fictional fixture with no private information.
        print(label + " generated title:", title)
        for i, paragraph in enumerate(paragraphs, 1):
            print(label + f" generated paragraph {i}:", paragraph)
        return original_check(title, paragraphs, factual_input)
    try:
        with patch.object(editorial, "_basic_checks", side_effect=debug_check):
            result = call(
                SOURCE_TITLE, SOURCE_PARAS, TITLE_RU, DRAFT_RU,
                api_key=api_key,
            )
    except EditorialError as exc:
        print(label + ": editorial rejected test:", str(exc))
        return False
    print(label + ": rewrite accepted")
    print(label + " title:", result.title)
    print(label + " paragraphs:", len(result.paragraphs))
    for number, paragraph in enumerate(result.paragraphs, 1):
        print(label + f" paragraph {number}:", paragraph)
    return True

if __name__ == "__main__":
    check("Groq", os.getenv("GROQ_API_KEY", "").strip(), edit_with_groq)
    check(
        "Gemini",
        (os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")).strip(),
        edit_with_gemini,
    )
