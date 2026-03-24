from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import requests

from .io_ops import HTML_BREAK_RE

OPEN_METEO_GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
LAT_LON_RE = re.compile(r"(?P<lat>[+-]?\d{1,2}(?:\.\d+)?)\s*[,;/]\s*(?P<lon>[+-]?\d{1,3}(?:\.\d+)?)")


def geocode_place(
    value: str,
    *,
    api_key: str,
    cache: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    cleaned = HTML_BREAK_RE.sub(", ", value).strip()
    if not cleaned or not api_key:
        return None
    resolved_cache = cache if cache is not None else {}
    if cleaned in resolved_cache:
        return resolved_cache[cleaned]
    params = {
        "name": cleaned,
        "count": "1",
        "language": "en",
        "format": "json",
        "apikey": api_key,
    }
    url = f"{OPEN_METEO_GEOCODING_API}?{urllib.parse.urlencode(params)}"
    try:
        response = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        resolved_cache[cleaned] = None
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        resolved_cache[cleaned] = None
        return None
    first = results[0]
    try:
        latitude = float(first["latitude"])
        longitude = float(first["longitude"])
    except (KeyError, TypeError, ValueError):
        resolved_cache[cleaned] = None
        return None
    address_parts = [first.get("name", ""), first.get("admin1", ""), first.get("country", "")]
    place = {
        "name": str(first.get("name") or cleaned)[:200],
        "address": ", ".join(part for part in address_parts if part)[:2000],
        "lat": latitude,
        "lon": longitude,
    }
    resolved_cache[cleaned] = place
    return place


def parse_place(
    value: str,
    *,
    api_key: str = "",
    cache: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    cleaned = HTML_BREAK_RE.sub(", ", value).strip()
    if not cleaned:
        return None
    match = LAT_LON_RE.search(cleaned)
    if match:
        latitude = float(match.group("lat"))
        longitude = float(match.group("lon"))
        without_coords = LAT_LON_RE.sub("", cleaned)
        without_coords = re.sub(r"\(\s*\)", "", without_coords)
        without_coords = re.sub(r"\s*[,;/]\s*[,;/]\s*", ", ", without_coords)
        parts = [part.strip(" ,;/") for part in re.split(r"[,;]", without_coords) if part.strip(" ,;/")]
        name = parts[0] if parts else cleaned
        return {
            "name": name[:200],
            "address": ", ".join(parts)[:2000],
            "lat": latitude,
            "lon": longitude,
        }
    return geocode_place(cleaned, api_key=api_key, cache=cache)
