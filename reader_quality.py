"""Editorial quality rubric for Russian Serbia24 Telegram news.

A quality score is a model-assisted editorial screening estimate, NOT a
guarantee that facts have been independently verified. Fail closed when
the reviewer does not give a complete credible assessment.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

CRITERIA = ("clarity", "completeness", "russian", "headline", "fidelity")
CRITICAL_ISSUES = frozenset((
    "unsupported_claim", "wrong_actor", "wrong_status", "wrong_date",
    "wrong_amount", "misattributed_quote", "contradiction",
    "missing_essential_condition", "unresolved_referent",
))
BAD_TRANSLATION = (
    (r"\bпроточн\w*\s+(?:кот[её]л|бойлер)\w*", "Буквальная сербская метафора"),
    (r"\bактивировал[аио]?\s+плат[её]жн\w*\s+документ", "Неясное описание финансовой операции"),
    (r"\bперевод\w*\s+на\s+проверк\w*\s+компетентност", "Неясный статус кадровой процедуры"),
    (r"\bдоход\w*\s+в\s+доходн\w*", "Тавтология"),
)


class QualityRejected(ValueError):
    """News did not reach the minimum 8/10 editorial quality target."""


@dataclass(frozen=True)
class QualityGrade:
    scores: dict[str, int]
    issues: tuple[str, ...]

    @property
    def total(self) -> int:
        return sum(self.scores.values())


def unidiomatic_phrases(title: str, paragraphs: list[str] | tuple[str, ...]) -> list[str]:
    """Conservative fail-fast checks based on actual failed channel posts."""
    full = " ".join((title, *paragraphs)).lower()
    return [label for pattern, label in BAD_TRANSLATION if re.search(pattern, full, re.I)]


def validate_grade(
    value: object, title: str, paragraphs: list[str] | tuple[str, ...],
    minimum: int = 8,
) -> QualityGrade:
    if not isinstance(value, dict):
        raise QualityRejected("Нет редакторской оценки")
    scores = value.get("scores")
    issues = value.get("critical_issues")
    if not isinstance(scores, dict) or set(scores) != set(CRITERIA):
        raise QualityRejected("Не заполнены пять критериев оценки")
    if not isinstance(issues, list) or not all(isinstance(x, str) for x in issues):
        raise QualityRejected("Не заполнена проверка критических ошибок")
    if any(type(scores[k]) is not int or not 0 <= scores[k] <= 2 for k in CRITERIA):
        raise QualityRejected("Оценки должны быть целыми числами от 0 до 2")
    unknown = set(issues) - CRITICAL_ISSUES
    if unknown:
        raise QualityRejected("Неизвестный код ошибки редакционной оценки")
    result = QualityGrade(dict(scores), tuple(issues))
    if result.issues:
        raise QualityRejected(
            "Критическая смысловая ошибка: " + ", ".join(result.issues)
        )
    if result.scores["fidelity"] != 2:
        raise QualityRejected("Недостаточно подтверждена точность изложения")
    if result.scores["clarity"] < 1 or result.scores["russian"] < 1:
        raise QualityRejected("Текст непонятен или плохо написан по-русски")
    problems = unidiomatic_phrases(title, paragraphs)
    if problems:
        raise QualityRejected("Механический перевод: " + ", ".join(problems))
    if result.total < minimum:
        raise QualityRejected(f"Редакторская оценка {result.total}/10 ниже порога {minimum}/10")
    return result


def source_grounded_status_guard(source: str, title: str, paragraphs: list[str] | tuple[str, ...]) -> None:
    """Catch an especially dangerous source -> outcome mistranslation.

    If an inspector has merely been called to an assessment for a possible
    future transfer, do not claim the transfer has already taken place.
    """
    original = source.lower()
    finished = " ".join((title, *paragraphs)).lower()
    if not (
        re.search(r"inspektor|inspektor[au]|bosi[cć]", original)
        and re.search(r"prover|proveru|testir|procen|procenu", original)
        and re.search(r"moguć|moguc|eventual|ukoliko|ako|najav", original)
    ):
        return

    # Inspect individual sentences so a conditional in one paragraph cannot
    # excuse an unconditional claim in another ("Это будет второй перевод").
    sentences = [title, *re.split(r"(?<=[.!?])\s+", " ".join(paragraphs))]
    assertion = re.compile(
        r"\b(?:перевели|уже переводят|уже перевед[её]н|перевод состоялся)\b"
        r"|\b(?:это|он|она|сотрудник)\s+будет\b.{0,80}\bперевод\w*"
        r"|\bбудет\s+перевед[её]н\w*"
        r"|\bвторой\s+перевод\b"
        r"|\bзаконност\w*\s+перевода\b",
        re.I,
    )
    conditional = re.compile(
        r"\bесли\b|\bможет\b|\bвозможн\w*|\bпредполага\w*|"
        r"\bпланиру\w*|\bв\s+случае\b|\bпри\s+условии\b|"
        r"\bпотенциальн\w*|\bпока\s+не\s+реш\w*",
        re.I,
    )
    for sentence in sentences:
        if assertion.search(sentence) and not conditional.search(sentence):
            raise QualityRejected(
                "Возможный перевод инспектора нельзя описывать как гарантированный или состоявшийся"
            )
