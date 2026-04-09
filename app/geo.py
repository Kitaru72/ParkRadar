from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from .config import DEMO_LOCATIONS


GOOGLE_AT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
FLOAT_PAIR_RE = re.compile(r"(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)")


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def resolve_demo_location(query: str) -> dict[str, Any] | None:
    normalized = _normalize(query)
    if normalized in DEMO_LOCATIONS:
        item = DEMO_LOCATIONS[normalized]
        return {
            "query": query,
            "resolved_address": item["address"],
            "lat": item["lat"],
            "lon": item["lon"],
            "source": "demo",
        }
    return None


def parse_map_url(query: str) -> dict[str, Any] | None:
    text = query.strip()
    if not text.startswith(("http://", "https://")):
        return None

    parsed = urlparse(text)
    decoded = unquote(text)

    match = GOOGLE_AT_RE.search(decoded)
    if match:
        return {
            "query": query,
            "resolved_address": text,
            "lat": float(match.group(1)),
            "lon": float(match.group(2)),
            "source": "maps_url",
        }

    qs = parse_qs(parsed.query)
    if "ll" in qs:
        pair = qs["ll"][0].split(",")
        if len(pair) == 2:
            lon, lat = pair
            return {
                "query": query,
                "resolved_address": text,
                "lat": float(lat),
                "lon": float(lon),
                "source": "maps_url",
            }
    if "q" in qs:
        candidate = qs["q"][0]
        match = FLOAT_PAIR_RE.search(candidate)
        if match:
            return {
                "query": query,
                "resolved_address": text,
                "lat": float(match.group(1)),
                "lon": float(match.group(2)),
                "source": "maps_url",
            }

    match = FLOAT_PAIR_RE.search(decoded)
    if match:
        return {
            "query": query,
            "resolved_address": text,
            "lat": float(match.group(1)),
            "lon": float(match.group(2)),
            "source": "maps_url",
        }
    return None


async def geocode_query(query: str) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("Пустой адрес")

    demo = resolve_demo_location(query)
    if demo:
        return demo

    parsed_url = parse_map_url(query)
    if parsed_url:
        return parsed_url

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "jsonv2", "limit": 1}
    headers = {"User-Agent": "ParkRadar Hackathon Demo/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params, timeout=20) as response:
            if response.status != 200:
                raise ValueError("Не удалось разрешить адрес")
            payload = await response.json()
    if not payload:
        raise ValueError("Адрес не найден")
    first = payload[0]
    return {
        "query": query,
        "resolved_address": first.get("display_name", query),
        "lat": float(first["lat"]),
        "lon": float(first["lon"]),
        "source": "nominatim",
    }
