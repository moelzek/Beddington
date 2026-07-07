"""Outside weather via Open-Meteo (free, keyless) for the conversation demo.

This is the product's only internet-bound call and is off unless
``[assistant.weather] enabled`` is set. The fetched numbers are turned into one
deterministic sentence; the LLM only ever re-voices that sentence (same
numbers-from-code, words-from-model split as the sensor answers).
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from .config import WeatherConfig

_FETCH_TIMEOUT_SECONDS = 4.0

# WMO weather interpretation codes -> plain descriptions.
_WMO_CODES: dict[int, str] = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with rime",
    51: "lightly drizzling",
    53: "drizzling",
    55: "drizzling heavily",
    61: "lightly raining",
    63: "raining",
    65: "raining heavily",
    66: "raining and icy",
    67: "raining and icy",
    71: "lightly snowing",
    73: "snowing",
    75: "snowing heavily",
    77: "snowing",
    80: "showery",
    81: "showery",
    82: "showery and heavy",
    85: "snow-showery",
    86: "snow-showery",
    95: "thundery",
    96: "thundery with hail",
    99: "thundery with hail",
}

# (expires_at_monotonic, line)
_CACHE: dict[tuple[float, float], tuple[float, str]] = {}


def weather_line(config: WeatherConfig, fetch: Any | None = None) -> str | None:
    """One deterministic sentence about the weather outside, or None.

    Cached for ``cache_seconds`` so chat turns don't hammer the API.
    """
    if not config.enabled:
        return None
    key = (config.latitude, config.longitude)
    cached = _CACHE.get(key)
    now = time.monotonic()
    if cached is not None and now < cached[0]:
        return cached[1]
    fetcher = fetch or _fetch_open_meteo
    try:
        data = fetcher(config)
        line = _line_from_data(data)
    except Exception:
        return cached[1] if cached is not None else None
    if line is None:
        return cached[1] if cached is not None else None
    _CACHE[key] = (now + config.cache_seconds, line)
    return line


def _fetch_open_meteo(config: WeatherConfig) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={config.latitude}&longitude={config.longitude}"
        "&current=temperature_2m,precipitation,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=auto&forecast_days=1"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "beddington/0.1"})
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        return json.load(response)


def _line_from_data(data: dict) -> str | None:
    current = data.get("current") or {}
    temperature = current.get("temperature_2m")
    code = current.get("weather_code")
    if temperature is None or code is None:
        return None
    description = _WMO_CODES.get(int(code), "changeable")
    parts = [
        f"Outside it is {description} and about {round(float(temperature))} degrees Celsius"
    ]
    daily = data.get("daily") or {}
    highs = daily.get("temperature_2m_max") or []
    rain_chances = daily.get("precipitation_probability_max") or []
    if highs:
        parts.append(f"with a high of about {round(float(highs[0]))} today")
    if rain_chances and rain_chances[0] is not None:
        chance = int(rain_chances[0])
        if chance >= 30:
            parts.append(f"and a {chance} percent chance of rain")
    return ", ".join(parts) + "."


def is_weather_question(question: str) -> bool:
    """Cheap lexical check so outdoor questions don't hit the room sensors."""
    words = set(question.lower().replace("'", " ").split())
    hints = {
        "weather", "outside", "outdoors", "rain", "raining", "rainy", "sunny",
        "sunshine", "snow", "snowing", "windy", "forecast", "umbrella",
        "cloudy", "cold", "warm", "hot",
    }
    if "weather" in words or "forecast" in words or "umbrella" in words:
        return True
    return bool(words & {"outside", "outdoors"}) and bool(words & hints)
