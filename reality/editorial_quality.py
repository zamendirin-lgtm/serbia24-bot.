"""Fail-closed editorial rules for the Reality Telegram channel.

No model-generated facts, mid-word clipping or unrelated animal photographs.
"""
from __future__ import annotations

import html
import re

MAX_TITLE = 118
MAX_CAPTION = 1024
# Animal photos require an identifiable animal, not a generic "wildlife" match.
ANIMALS = [
    (r"\b(?:peregrine(?:\s+falcons?)?|falco\s+peregrinus|сапсан\w*)\b",
     "peregrine falcon", ("peregrine", "falco peregrinus")),
    (r"\b(?:cheetahs?|гепард\w*)\b", "cheetah", ("cheetah", "acinonyx")),
    (r"\b(?:elephants?|слон\w*|слонен\w*)\b", "elephant", ("elephant", "loxodonta", "elephas")),
    (r"\b(?:tigers?|тигр\w*)\b", "tiger", ("tiger", "panthera tigris")),
    (r"\b(?:lions?|льв\w*|лев\b)\b", "lion", ("lion", "panthera leo")),
    (r"\b(?:sharks?|акул\w*)\b", "shark", ("shark",)),
    (r"\b(?:whales?|кит\w*)\b", "whale", ("whale",)),
    (r"\b(?:octopuses?|осьминог\w*)\b", "octopus", ("octopus",)),
    (r"\b(?:spiders?|паук\w*)\b", "spider", ("spider",)),
    (r"\b(?:frogs?|лягушк\w*)\b", "frog", ("frog",)),
    (r"\b(?:bees?|пчел\w*)\b", "honey bee", ("bee", "apis mellifera")),
]
# These Wikimedia subject terms are allowed as generic illustrations.
OTHER_SUBJECTS = {
    "nebula": ("nebula",), "galaxy": ("galaxy", "galaxies"),
    "planet": ("planet", "jupiter", "saturn", "pluto", "neptune", "uranus"),
    "planet mars": ("mars", "martian"), "moon": ("moon", "lunar"),
    "star": ("star", "stellar"), "black hole": ("black hole",),
    "dinosaur skeleton": ("dinosaur", "fossil"), "fossil": ("fossil",),
    "archaeological excavation": ("archaeolog", "excavation"),
    "ancient ruins": ("ruins", "ruin"), "ocean": ("ocean", "sea"),
    "deep sea": ("deep sea", "ocean"), "bird": ("bird", "aves"),
    "forest": ("forest", "woods"), "plants": ("plant", "botan"),
    "mushroom": ("mushroom", "fung"), "fungus": ("fung", "mushroom"),
    "volcano": ("volcano", "volcanic"), "earthquake": ("earthquake",),
    "aurora borealis": ("aurora", "northern lights"), "clouds": ("cloud",),
    "human brain": ("brain", "cerebr"), "neuron": ("neuron",),
    "sleep": ("sleep",), "human heart": ("heart", "cardiac"),
    "bacteria": ("bacter", "microbe"), "DNA molecule": ("dna",),
    "DNA": ("dna",), "cell biology": ("cell",),
    "robot": ("robot",), "quantum physics": ("quantum",),
    "computer": ("computer",),
}
ANIMAL_QUERIES = {query: terms for _, query, terms in ANIMALS}
GENERIC_QUERIES = {"wildlife", "animal", "animals", "nature", "ancient"}
SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]+(?=\s|$)", re.S)


def animal_subject(title: str, summary: str = ""):
    """Use the full RSS text; generic news headlines often hide the species."""
    haystack = title + " " + summary
    for pattern, query, _ in ANIMALS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return ("animals", query)
    return None


def photo_matches(query: str, image_title: str) -> bool:
    """Check the Commons filename, not only a possibly misleading search hit."""
    title = re.sub(r"[_-]+", " ", image_title).casefold()
    if query.casefold() in GENERIC_QUERIES:
        return False
    terms = ANIMAL_QUERIES.get(query) or OTHER_SUBJECTS.get(query)
    if not terms:
        # Unknown subject: no generic photo is reliable.
        return False
    return any(re.search(r"(?<![a-z])" + re.escape(term.casefold()) + r"(?![a-z])", title)
               for term in terms)


def _complete_sentences(text: str):
    s = re.sub(r"\s+", " ", (text or "")).strip()
    return [m.group().strip() for m in SENTENCE_RE.finditer(s)
            if len(m.group().strip()) >= 45]


def english_excerpt(raw: str, max_length: int = 570) -> str:
    """Extract only FULL source sentences, never trim in the middle of a fact."""
    selected = []
    for sentence in _complete_sentences(raw):
        proposal = " ".join(selected + [sentence])
        if len(proposal) > max_length:
            break
        selected.append(sentence)
        if len(selected) == 2:
            break
    return " ".join(selected)


def russian_sentences(raw: str) -> list[str]:
    return _complete_sentences(raw)


def compose_caption(title: str, translated: str, footer: str, emoji: str = "🔬") -> str:
    """Only full headline and full body sentences with intact HTML footer."""
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title or len(title) > MAX_TITLE:
        return ""
    if re.search(r"\b(?:изме|которы|посредств)\s*$", title, re.IGNORECASE):
        return ""
    sentences = russian_sentences(translated)
    if not sentences:
        return ""
    head = f"{emoji} <b>{html.escape(title.rstrip())}</b>\n\n"
    tail = "\n\n" + footer
    if len(head + tail) >= MAX_CAPTION:
        return ""
    selected = []
    for sentence in sentences:
        proposal = head + html.escape(" ".join(selected + [sentence])) + tail
        if len(proposal) > MAX_CAPTION:
            break
        selected.append(sentence)
        if len(selected) >= 3:
            break
    if not selected or len(" ".join(selected)) < 65:
        return ""
    return head + html.escape(" ".join(selected)) + tail
