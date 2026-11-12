"""Reject incomplete news references that make readers open the source.

A reader should not have to guess which documentary is discussed when a
news item claims to be about a film premiere. Conservative and specific:
reject ambiguous film-premiere references, without inventing a title.
"""
from __future__ import annotations
import re

class MissingContextError(ValueError):
    """Key identifying information is missing from the proposed post."""


PREMIERE = re.compile(
    r"премьер\w*.{0,100}(?:фильм\w*|документальн\w*\s+картин\w*)"
    r"|(?:фильм\w*|документальн\w*\s+картин\w*).{0,65}премьер\w*",
    flags=re.I | re.S,
)
NAMED_FILM = re.compile(
    r"(?:фильм\w*|картин\w*|лент\w*|документальн\w*\s+фильм\w*)"
    r"\s*(?:под\s+названием\s*)?[«„\"]([^»“\"]{5,120})[»“\"]",
    flags=re.I,
)

def missing_film_identity(title: str, paragraphs: list[str] | tuple[str, ...]) -> bool:
    """A premiere is mentioned, but the film is never actually named."""
    combined = "\n\n".join([title, *paragraphs])
    if not PREMIERE.search(combined):
        return False
    return not bool(NAMED_FILM.search(combined))


def ensure_resolved_context(title: str, paragraphs: list[str] | tuple[str, ...]) -> None:
    if missing_film_identity(title, paragraphs):
        raise MissingContextError(
            "Упомянута премьера фильма, но название фильма не указано"
        )
