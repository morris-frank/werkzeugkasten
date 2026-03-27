from __future__ import annotations

import json
import os
import re
import urllib.parse
from typing import Any

import requests

from werkzeugkasten_engine.internal import HTML_BREAK_RE, Cache, LocalCache

OPEN_METEO_GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
LAT_LON_RE = re.compile(r"(?P<lat>[+-]?\d{1,2}(?:\.\d+)?)\s*[,;/]\s*(?P<lon>[+-]?\d{1,3}(?:\.\d+)?)")


def _open_meteo_api_key() -> str:
    return os.environ.get("WERKZEUGKASTEN_OPEN_METEO_API_KEY", "") or os.environ.get("OPEN_METEO_API_KEY", "")


def _geocode_with_open_meteo(value: str, /) -> dict[str, Any] | None:
    if api_key := _open_meteo_api_key() is None:
        return None
    response = requests.get(
        OPEN_METEO_GEOCODING_API,
        params={
            "name": value,
            "count": "1",
            "language": "en",
            "format": "json",
            "apikey": api_key,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    try:

        payload = response.json()
        results = payload.get("results")
        first = results[0]
        latitude = float(first["latitude"])
        longitude = float(first["longitude"])
        address_parts = [first.get("name", ""), first.get("admin1", ""), first.get("country", "")]
        place = {
            "name": str(first.get("name") or value)[:200],
            "address": ", ".join(part for part in address_parts if part)[:2000],
            "lat": latitude,
            "lon": longitude,
        }
        return place
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _as_coordinates(value: str) -> dict[str, Any] | None:
    if match := LAT_LON_RE.search(value):
        latitude = float(match.group("lat"))
        longitude = float(match.group("lon"))
        without_coords = LAT_LON_RE.sub("", value)
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


def geocode_place(
    value: str,
    *,
    api_key: str = "",
) -> dict[str, Any] | None:
    if result := _as_coordinates(value):
        return result

    return _geocode_with_open_meteo(value)
