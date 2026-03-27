from __future__ import annotations

import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests
from markitdown import MarkItDown

from werkzeugkasten_engine.internal import Source, n_threads, url_timeout
from werkzeugkasten_engine.internal.cache import Cache, LocalCache


def _jina_api_key() -> str:
    key = os.environ.get("WERKZEUGKASTEN_JINA_API_KEY", "") or os.environ.get("JINA_API_KEY", "") or os.environ.get("JINA_API_TOKEN", "")
    return key.strip()


_CONTENT_SEPARATOR = "\n\n"
_DOCUMENT_CONTENT_TYPES = {
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


def _maybe_web_content(s: Source) -> str | None:
    if not isinstance(s, str):
        return None
    url = s.strip()
    if not url.startswith(("http:", "https:")):
        return None

    # 1. Check by extension
    path = url2pathname(urlparse(url).path)
    extension = Path(path).suffix.lower()
    content_type, _ = mimetypes.guess_type(extension)
    if content_type in _DOCUMENT_CONTENT_TYPES:
        return None

    if url_timeout() <= 0:
        return url

    # 2. Check by content type
    try:
        r = requests.head(url, allow_redirects=True, timeout=url_timeout())
        ct = r.headers.get("Content-Type")
        if ct:
            if ct.split(";", 1)[0].strip() not in _DOCUMENT_CONTENT_TYPES:
                return url
            return None
    except requests.RequestException:
        return url
    return url


def _jina_fetch(url: str) -> str:
    request_url = f"https://r.jina.ai/{url}"
    headers = {
        "X-Engine": "direct",
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "referenced",
    }
    api_key = _jina_api_key().strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.get(request_url, headers=headers, timeout=30)
    body = response.text.strip()
    return body


def _reference_converter(as_markdown: bool) -> Callable[[Source], str]:
    def converter(source: Source) -> str:
        if content := cache[source]:
            return content
        if url := _maybe_web_content(source):
            try:
                content = _jina_fetch(url)
            except Exception as exc:
                pass
        if content is None:
            content = md.convert(source).markdown if as_markdown else source
        if as_markdown:
            cache[source] = content
        return content

    cache = LocalCache(Cache.CONTENT)
    md = MarkItDown()

    return converter


def get_content(sources: list[Source], /, *, as_markdown: bool = True) -> str:
    if not sources:
        return ""
    converter = _reference_converter(as_markdown)
    with ThreadPoolExecutor(max_workers=min(n_threads(), len(sources))) as executor:
        contents = list(executor.map(converter, sources))

    return _CONTENT_SEPARATOR.join(contents)
