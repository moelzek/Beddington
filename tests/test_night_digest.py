from __future__ import annotations

import re

from beddington.night_digest import summarise_night

# A night digest must never claim sleep/safety/health.
_BANNED = {"asleep", "sleeping", "slept", "safe", "healthy", "fine", "normal", "well"}


def _series(**columns: list[list[float]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, points in columns.items():
        out[key] = {
            "label": key,
            "unit": "",
            "bool": key in ("person_present", "motion_detected"),
            "points": points,
        }
    return out


def test_summarise_night_reports_facts() -> None:
    series = _series(
        room_temperature_c=[[0.0, 19.0], [3600.0, 23.0]],
        room_humidity_pct=[[0.0, 45.0], [3600.0, 50.0]],
        person_present=[[0.0, 1.0], [3600.0, 1.0]],
        motion_detected=[[0.0, 0.0], [1800.0, 1.0], [3600.0, 0.0]],
    )
    text = summarise_night(series, time_label=lambda ts: "04:00")
    assert "Temperature 19 to 23" in text
    assert "Humidity 45 to 50" in text
    assert "nearby" in text.lower()
    assert "movement" in text.lower()
    assert "coolest around 04:00" in text


def test_summarise_night_adds_trend_lines() -> None:
    series = _series(
        room_temperature_c=[[0.0, 20.0], [3600.0, 21.0]],
    )
    text = summarise_night(
        series,
        aggregates={
            "stir_hours": [(2, 3), (4, 1)],
            "soothe_tallies": [("rain", 2, 3), ("waves", 1, 1)],
        },
    )

    assert "• Rayan usually stirs around ~2am (best guess)." in text
    assert "• When rain played, Rayan quieted 2/3 times (best guess)." in text


def test_summarise_night_skips_sparse_trends() -> None:
    series = _series(
        room_temperature_c=[[0.0, 20.0], [3600.0, 21.0]],
    )
    text = summarise_night(
        series,
        aggregates={
            "stir_hours": [(2, 1)],
            "soothe_tallies": [("rain", 1, 1)],
        },
    )

    assert "usually stirs" not in text
    assert "Rayan quieted" not in text


def test_summarise_night_makes_no_safety_claim() -> None:
    series = _series(
        room_temperature_c=[[0.0, 20.0], [60.0, 20.0]],
        radar_respiratory_rate=[[0.0, 16.0], [60.0, 16.0]],
        radar_heart_rate_bpm=[[0.0, 90.0], [60.0, 90.0]],
    )
    text = summarise_night(
        series,
        aggregates={
            "stir_hours": [(3, 2)],
            "soothe_tallies": [("safe_song", 2, 2), ("rain", 1, 2)],
        },
    )
    words = set(re.findall(r"[a-z]+", text.lower()))
    assert words.isdisjoint(_BANNED)
    # vitals line is present as rough bench readings, with no medical disclaimer
    assert "rough bench readings" in text.lower()
    assert "not a medical reading" not in text.lower()
    assert "safe song" not in text.lower()


def test_summarise_night_empty() -> None:
    assert "enough history" in summarise_night({})
