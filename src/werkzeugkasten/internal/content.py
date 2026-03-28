from __future__ import annotations

import mimetypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, Callable, Union
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests
from markitdown import MarkItDown

from ..internal.env import E, E_int
from .cache import cache

Source = Union[str, requests.Response, Path, BinaryIO]

__DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/rtf",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/epub+zip",
}


def _maybe_document_url(source: Source) -> str | None:
    """Heuristically determine if the source is a URL pointing to a document. Without downloading the content."""
    if not isinstance(source, str):
        return None
    url = source.strip()
    if not url.startswith(("http:", "https:")):
        return None

    # 1. Check by extension
    path = url2pathname(urlparse(url).path)
    extension = Path(path).suffix.lower()
    content_type, _ = mimetypes.guess_type(extension)
    if content_type in __DOCUMENT_CONTENT_TYPES:
        return None

    if E_int["DOCUMENT_URL_TIMEOUT", 5] <= 0:
        return url

    # 2. Check by content type
    try:
        r = requests.head(url, allow_redirects=True, timeout=E_int["DOCUMENT_URL_TIMEOUT", 5])
        ct = r.headers.get("Content-Type")
        if ct:
            if ct.split(";", 1)[0].strip() not in __DOCUMENT_CONTENT_TYPES:
                return url
            return None
    except requests.RequestException:
        return url
    return url


def _jina_fetch(url: str) -> str:
    request_url = E["JINA_REQUEST_URL", "https://r.jina.ai/{url}"]
    headers = {
        "X-Engine": E["JINA_ENGINE", "direct"],
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "referenced",
    }
    if api_key := E["jina_api_key"]:
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.get(request_url.format(url=url), headers=headers, timeout=E_int["JINA_TIMEOUT", 30])
    body = response.text.strip()
    return body


def _content_extractor(as_markdown: bool) -> Callable[[Source], str]:
    def extractor(source: Source) -> str:
        if content := cache[source]:
            return content
        if url := _maybe_document_url(source):
            try:
                content = _jina_fetch(url)
            except Exception as exc:
                pass
        if content is None:
            content = MarkItDown().convert(source).markdown if as_markdown else source
        if as_markdown:
            cache[source] = content
        return content

    return extractor


def get_content(sources: list[Source], /, *, as_markdown: bool = True) -> str:
    if not sources:
        return ""
    extractor = _content_extractor(as_markdown)
    with ThreadPoolExecutor(max_workers=min(E_int["CONTENT_THREADS", 4], len(sources))) as executor:
        contents = list(executor.map(extractor, sources))

    return E["CONTENT_SEPARATOR", "\n\n"].join(contents)
