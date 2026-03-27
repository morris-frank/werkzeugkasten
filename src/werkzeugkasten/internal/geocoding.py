from __future__ import annotations

import json
import re
from typing import Any

import requests

from ..internal.env import open_meteo_api_key

_OPEN_METEO_GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
_LAT_LON_RE = re.compile(r"(?P<lat>[+-]?\d{1,2}(?:\.\d+)?)\s*[,;/]\s*(?P<lon>[+-]?\d{1,3}(?:\.\d+)?)")


def _geocode_with_open_meteo(value: str, /) -> dict[str, Any] | None:
    if not open_meteo_api_key:
        return None
    response = requests.get(
        _OPEN_METEO_GEOCODING_API,
        params={
            "name": value,
            "count": "1",
            "language": "en",
            "format": "json",
            "apikey": open_meteo_api_key,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    try:
        payload = response.json()
        results = payload.get("results") or []
        first = results[0]
        latitude = float(first["latitude"])
        longitude = float(first["longitude"])
        address_parts = [first.get("name", ""), first.get("admin1", ""), first.get("country", "")]
        return {
            "name": str(first.get("name") or value)[:200],
            "address": ", ".join(part for part in address_parts if part)[:2000],
            "lat": latitude,
            "lon": longitude,
        }
    except (IndexError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _as_coordinates(value: str) -> dict[str, Any] | None:
    if not (match := _LAT_LON_RE.search(value)):
        return None
    latitude = float(match.group("lat"))
    longitude = float(match.group("lon"))
    without_coords = _LAT_LON_RE.sub("", value)
    without_coords = re.sub(r"\(\s*\)", "", without_coords)
    without_coords = re.sub(r"\s*[,;/]\s*[,;/]\s*", ", ", without_coords)
    parts = [part.strip(" ,;/") for part in re.split(r"[,;]", without_coords) if part.strip(" ,;/")]
    name = parts[0] if parts else value
    return {
        "name": name[:200],
        "address": ", ".join(parts)[:2000],
        "lat": latitude,
        "lon": longitude,
    }


_geocode_cache: dict[str, dict[str, Any] | None] = {}


def geocode_place(value: str, /) -> dict[str, Any] | None:
    normalized = value.strip()
    if not normalized:
        return None
    if result := _geocode_cache.get(normalized):
        return result
    result = _as_coordinates(normalized) or _geocode_with_open_meteo(normalized)
    if result is not None:
        _geocode_cache[normalized] = result
    return result
