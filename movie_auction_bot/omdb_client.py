"""
Thin async client for the OMDb API (https://www.omdbapi.com/), with a local
on-disk cache so we don't re-fetch the same title every time it comes up.

OMDb's free tier is 1,000 requests/day, which is far more than a hobby
group needs -- but caching means we practically never hit it after a
universe's titles have been resolved once.
"""
import json
import os
from pathlib import Path
from typing import Optional

import aiohttp

from config import OMDB_API_KEY

CACHE_PATH = Path(__file__).parent / "data" / "omdb_cache.json"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _parse_money(value: str) -> Optional[int]:
    """Turn OMDb's '$858,373,000' (or 'N/A') into an int, or None."""
    if not value or value == "N/A":
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_float(value: str) -> Optional[float]:
    if not value or value == "N/A":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str) -> Optional[int]:
    if not value or value == "N/A":
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _extract_rotten_tomatoes(ratings: list) -> Optional[float]:
    """OMDb returns a Ratings array like [{'Source': 'Rotten Tomatoes', 'Value': '94%'}, ...]."""
    for entry in ratings or []:
        if entry.get("Source") == "Rotten Tomatoes":
            val = entry.get("Value", "").replace("%", "").strip()
            try:
                return float(val)
            except ValueError:
                return None
    return None


class TitleNotFound(Exception):
    pass


class OMDbClient:
    BASE_URL = "https://www.omdbapi.com/"

    def __init__(self):
        self.cache = _load_cache()

    async def fetch_title(self, title: str, media_type: Optional[str] = None) -> dict:
        """
        Look up a title by name. media_type can be 'movie', 'series', or None (auto).
        Returns a normalized dict; raises TitleNotFound if OMDb has no match.
        Results are cached on disk keyed by "title|type".
        """
        cache_key = f"{title.lower().strip()}|{media_type or 'any'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        params = {"apikey": OMDB_API_KEY, "t": title, "plot": "short", "r": "json"}
        if media_type:
            params["type"] = media_type

        async with aiohttp.ClientSession() as session:
            async with session.get(self.BASE_URL, params=params, timeout=15) as resp:
                data = await resp.json()

        if data.get("Response") == "False":
            raise TitleNotFound(f"OMDb couldn't find '{title}' ({data.get('Error')})")

        record = {
            "title": data.get("Title"),
            "year": data.get("Year"),
            "type": data.get("Type"),  # "movie" or "series"
            "imdb_id": data.get("imdbID"),
            "imdb_rating": _parse_float(data.get("imdbRating")),
            "imdb_votes": _parse_int(data.get("imdbVotes")),
            "rotten_tomatoes": _extract_rotten_tomatoes(data.get("Ratings")),
            "box_office": _parse_money(data.get("BoxOffice")),
            "poster": data.get("Poster") if data.get("Poster") != "N/A" else None,
        }

        self.cache[cache_key] = record
        _save_cache(self.cache)
        return record

    def clear_cache_entry(self, title: str, media_type: Optional[str] = None) -> None:
        cache_key = f"{title.lower().strip()}|{media_type or 'any'}"
        if cache_key in self.cache:
            del self.cache[cache_key]
            _save_cache(self.cache)
