import beddington.weather as weather
from beddington.config import WeatherConfig
from beddington.weather import is_weather_question, weather_line


_SAMPLE = {
    "current": {"temperature_2m": 17.6, "weather_code": 61},
    "daily": {
        "temperature_2m_max": [21.3],
        "temperature_2m_min": [12.0],
        "precipitation_probability_max": [65],
    },
}


def setup_function(_):
    weather._CACHE.clear()


def _cfg(**kwargs) -> WeatherConfig:
    defaults = dict(enabled=True, latitude=51.5, longitude=-0.13)
    defaults.update(kwargs)
    return WeatherConfig(**defaults)


def test_weather_line_from_sample_data():
    line = weather_line(_cfg(), fetch=lambda config: _SAMPLE)
    assert line == (
        "Outside it is lightly raining and about 18 degrees Celsius, "
        "with a high of about 21 today, and a 65 percent chance of rain."
    )


def test_weather_line_disabled_returns_none():
    assert weather_line(_cfg(enabled=False), fetch=lambda config: _SAMPLE) is None


def test_weather_line_caches_and_survives_fetch_failure():
    calls = {"n": 0}

    def fetch(config):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("offline")
        return _SAMPLE

    cfg = _cfg(cache_seconds=0.0)  # expire immediately -> second call refetches
    first = weather_line(cfg, fetch=fetch)
    second = weather_line(cfg, fetch=fetch)  # fetch fails -> stale line reused
    assert first == second
    assert calls["n"] == 2


def test_weather_line_low_rain_chance_omitted():
    data = {
        "current": {"temperature_2m": 20.0, "weather_code": 0},
        "daily": {"temperature_2m_max": [24.0], "precipitation_probability_max": [10]},
    }
    line = weather_line(_cfg(), fetch=lambda config: data)
    assert line == (
        "Outside it is clear and about 20 degrees Celsius, with a high of about 24 today."
    )
    assert "rain" not in line


def test_is_weather_question():
    assert is_weather_question("what's the weather like today")
    assert is_weather_question("do I need an umbrella")
    assert is_weather_question("is it cold outside")
    assert not is_weather_question("what is the temperature")  # room reading
    assert not is_weather_question("is anyone in the room")
