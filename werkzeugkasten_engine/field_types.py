from __future__ import annotations

import re

QUESTION_WORDS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
}
LOCATION_TOKENS = ("location", "address", "adress", "city", "country", "region", "state")


def is_question_header(header: str) -> bool:
    text = header.strip().lower()
    if not text:
        return False
    if "?" in text:
        return True
    return text.split()[0] in QUESTION_WORDS


def question_header(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise ValueError("Question cannot be empty.")
    return normalized if normalized.endswith("?") else f"{normalized}?"


def object_type_from_header(header: str) -> str:
    text = re.sub(r"[_-]+", " ", header.strip().lower())
    text = re.sub(r"\s+", " ", text).strip()
    if text.endswith(" name") and len(text.split()) > 1:
        text = text[:-5].strip()
    if text in {"name", "title"}:
        return "object"
    return text or "object"


def is_location_header(header: str) -> bool:
    lowered = header.strip().lower()
    return any(token in lowered for token in LOCATION_TOKENS)
