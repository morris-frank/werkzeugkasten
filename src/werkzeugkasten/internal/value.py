from __future__ import annotations

import json
import re
import urllib.parse
from enum import IntEnum
from typing import Any

from rapidfuzz import fuzz

_QUESTION_WORDS = {
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

_OBJECT_TYPE_CANONICALS = {"name", "title", "[blank]", "object", "blank"}


_LOCATION_TOKENS = ("location", "address", "adress", "city", "country", "region", "state")
_HTML_BREAK_RE = re.compile(r"\s*<br\s*/?>\s*", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>,)\]]+|www\.[^\s<>,)\]]+", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_REF_RE = re.compile(r"\s*\(Ref\s+\d+\)\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s+")
_NEWLINES_RE = re.compile(r"\n+")
_DELIMITER_RE = re.compile(r"\s*(?:/|\+|,|;)\s*")  # Replace /, +, or ; with comma


class MdLink(IntEnum):
    URL = 1
    LABEL = 2


# TODO: !!! ExtensionDtype

# as_*
#   "If I read this as value of type X what do I get?"
#   functions are used to convert text to a canonical form.
#   They throw errors if cast fails.
#   They are destructive!
#   There is no check for any other possible canonical forms.

# maybe_*
#   "Can I read this as value of type X?"
#   functions are used to convert text to a canonical form.
#   They return None if cast fails.
#   So can be used in conditional statements.
#   There is no check for any other possible canonical forms.


# make V.as_* and V.maybe_*


def _remove_code_block(text: str | None, /) -> str:
    text = unwrap_text(text)
    lines = [line for line in map(str.strip, text.splitlines()) if not line.startswith("```") and not line.endswith("```")]
    return "\n".join(lines)


def _normalize_scalar(text: str, /) -> str:
    text = unwrap_text(text)
    if url := as_url(text):
        return url
    text = collapse_markdown_link(text, MdLink.URL)
    text = _REF_RE.sub("", text)
    text = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", text).strip()  # Remove URLs
    text = re.sub(r"\([^)]*\.[^)]*\)", "", text).strip()  # Remove file extensions
    text = _SPACES_RE.sub(" ", text)  # Replace multiple spaces with single space.

    if re.fullmatch(r"[A-Z0-9]{2,}", text):  # If text is all uppercase and has at least 2 chars
        return text
    if text.islower() and len(text.split()) <= 4:
        return " ".join(word if word.isupper() else word.capitalize() for word in text.split())
    return text


# FIXME: Only top-level delimiter is supported -> newlines with commas in the lines should split only on newlines
def as_list(text: str | None | list[str], /) -> list[str]:
    if isinstance(text, list):
        normList = text
    else:
        working = _NEWLINES_RE.sub(",", unwrap_text(text))  # Replace newlines with commas
        working = _HTML_BREAK_RE.sub(",", unwrap_text(text))  # Replace <br> with comma
        working = re.sub(r"\s*(?:/|\+|;)\s*", ",", working)  # Replace /, +, or ; with comma
        working = re.sub(r"\s*,\s*", ",", working.strip())  # Replace multiple commas with single comma
        normList = working.split(",")
    values = [_normalize_scalar(item) for item in normList if item.strip()]
    return list(dict.fromkeys(values))


def unwrap_text(text: str | None, /) -> str:
    text = str(text) or ""
    text = _HTML_BREAK_RE.sub("\n", text).strip()
    text = _SPACES_RE.sub(" ", text)  # Replace multiple spaces with single space
    return text


def is_empty(text: str | None, /) -> bool:
    return unwrap_text(text) == ""


def as_object_type(text: str | None, /) -> str:
    text = unwrap_text(text)
    text = re.sub(r"[_-]+", " ", text)  # Replace hyphens and underscores with spaces
    if text.lower().endswith(" name") and len(text.split()) > 1:
        text = text[:-5]
    if not text or text.lower() in _OBJECT_TYPE_CANONICALS:
        return "object"
    return text


def is_location_type(text: str | None, /) -> bool:
    object_type = as_object_type(text)
    return any(token in object_type for token in _LOCATION_TOKENS)


def _normalize_url(text: str | None, /) -> str:
    text = unwrap_text(text).strip("[]()")
    if text.startswith("www.") or not re.match(r"^[a-z]+://", text, re.IGNORECASE):
        text = f"https://{text}"
    parsed = urllib.parse.urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (key, val)
        for key, val in query_pairs
        if not key.lower().startswith("utm_") and "openai" not in key.lower() and "openai" not in val.lower()
    ]
    query = urllib.parse.urlencode(filtered_query)
    rebuilt = urllib.parse.urlunparse(("https", host, path.rstrip("/"), "", query, ""))
    return rebuilt.rstrip("/") if rebuilt.endswith("/") and path in {"", "/"} else rebuilt


def collapse_markdown_link(text: str, collapse: MdLink, /) -> str:
    text = unwrap_text(text).strip("[]()")
    collapsed = _MARKDOWN_LINK_RE.sub(lambda match: match.group(collapse), text)
    # FIXME: re-enable this
    # if collapse == MdLink.URL:
    #     return _normalize_url(collapsed)
    return collapsed


def as_urls(text: str | None, /) -> list[str]:
    text = unwrap_text(text)
    urls = [match.group(0) for match in _URL_RE.finditer(text)]
    urls.extend(match.group(2) for match in _MARKDOWN_LINK_RE.finditer(text))
    return list(set(map(_normalize_url, urls)))


def as_url(text: str | None, /) -> str | None:
    urls = as_urls(text)
    candidate = collapse_markdown_link(text, MdLink.URL)
    if candidate in urls:
        return candidate
    return None


def as_location(text: str | None, /) -> str:
    return collapse_markdown_link(text, MdLink.LABEL)


def as_json(text: str | None, /) -> dict[str, Any]:
    text = _remove_code_block(text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and start < end:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {}


def maybe_question(text: str | None, /) -> str | None:
    text = unwrap_text(text)
    if not text:
        return None
    if "?" in text:
        return text
    if text.split()[0].lower() in _QUESTION_WORDS:
        return text if text.endswith("?") else f"{text}?"
    return None


def str_contains(text: str | None, needle: str | None, /) -> bool:
    return unwrap_text(needle).lower() in unwrap_text(text).lower()


def as_canonical(candidate: str, canonicals: list[str]) -> str:
    lowered = candidate.lower()
    for canonical in canonicals:
        if canonical.lower() == lowered:
            return canonical
    best_score = 0.0
    best_value: str | None = None
    for canonical in canonicals:
        score = fuzz.ratio(candidate.lower(), canonical.lower())
        if score > best_score:
            best_score = score
            best_value = canonical
    if best_score >= 92:
        return best_value or candidate
    return candidate


def fuzz_equals(a: str | None, b: str | None, /) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    a, b = unwrap_text(a), unwrap_text(b)
    if a == b:
        return True
    # NOTE: 90 is the threshold for "fuzz equals"
    if fuzz.ratio(a, b) >= 90:
        return True
    return False
