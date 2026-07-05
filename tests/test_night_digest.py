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


def _event(kind: str, started: float, ended: float | None, detail: str = "") -> dict:
    return {"kind": kind, "started_ts": started, "ended_ts": ended, "detail": detail}


def test_summarise_events_covers_every_kind() -> None:
    from beddington.night_digest import summarise_events

    timeline = [
        _event("crying", 0.0, 240.0),
        _event("crying", 1000.0, 1030.0),
        _event("caregiver_present", 100.0, 400.0),
        _event("caregiver_present", 2000.0, 2300.0),
        _event("sound_played", 120.0, 120.0, "white_noise"),
        _event("sound_played", 1010.0, 1010.0, "white_noise · settling"),
        _event("room_warm", 0.0, 2400.0),
        _event("baby_not_visible", 500.0, 1220.0),
        _event("sensor_unavailable", 600.0, 700.0, "motion_detected"),
        _event("manual_note", 900.0, 900.0, "gave a feed"),
        _event("stirring", 50.0, 80.0),  # excluded: motion series covers it
    ]
    lines = summarise_events(timeline, time_label=lambda ts: "02:40", now_ts=3000.0)
    text = "\n".join(lines)
    assert "2 crying spells, the longest about 4 minutes" in text
    assert "Someone came into the room 2 times" in text
    assert "2 soothing sounds played (white noise ×2)" in text
    assert "ran warm for about 40 minutes" in text
    assert "camera could not see the cot for about 12 minutes" in text
    assert "motion_detected" in text
    assert "Note at 02:40: gave a feed" in text
    assert "stirring" not in text.lower()


def test_summarise_events_open_episode_uses_now() -> None:
    from beddington.night_digest import summarise_events

    lines = summarise_events(
        [_event("room_warm", 0.0, None)], now_ts=1800.0
    )
    assert lines == ["• The room ran warm for about 30 minutes."]


def test_summarise_events_empty_and_banned_words() -> None:
    from beddington.night_digest import summarise_events

    assert summarise_events(None) == []
    assert summarise_events([]) == []
    # A preset named with a banned word is dropped, not echoed.
    from beddington.night_digest import _BANNED_WORDS

    lines = summarise_events(
        [_event("sound_played", 0.0, 0.0, "sleep_well_lullaby")], now_ts=10.0
    )
    text = " ".join(lines).lower()
    assert all(word not in re.findall(r"[a-z]+", text) for word in _BANNED_WORDS)


def test_summarise_night_appends_event_lines() -> None:
    series = _series(room_temperature_c=[[0.0, 20.0], [3600.0, 21.0]])
    text = summarise_night(
        series,
        time_label=lambda ts: "03:00",
        timeline=[_event("crying", 100.0, 220.0)],
    )
    assert "1 crying spell" in text
    from beddington.night_digest import _BANNED_WORDS

    lowered = set(re.findall(r"[a-z]+", text.lower()))
    assert not (lowered & _BANNED_WORDS)


def test_summarise_night_events_without_series() -> None:
    text = summarise_night(
        {},
        time_label=lambda ts: "03:00",
        timeline=[_event("manual_note", 0.0, 0.0, "settled after a feed")],
    )
    assert "Here's what I noticed:" in text
    assert "settled after a feed" in text


def test_summarise_night_bills_open_events_to_last_reading() -> None:
    # Monitor died at t=3600 with the warm episode still open; the digest must
    # not bill the dead hours after the final reading.
    series = _series(room_temperature_c=[[0.0, 24.5], [3600.0, 24.5]])
    text = summarise_night(series, timeline=[_event("room_warm", 0.0, None)])
    assert "ran warm for about 60 minutes" in text


def test_summarise_night_quotes_manual_note_verbatim() -> None:
    # The parent's own words are the one deliberate banned-word carve-out:
    # notes are quoted verbatim with a "Note at" attribution, never rephrased.
    series = _series(room_temperature_c=[[0.0, 20.0], [3600.0, 20.0]])
    text = summarise_night(
        series,
        time_label=lambda ts: "02:10",
        timeline=[_event("manual_note", 100.0, 100.0, "slept well after a feed")],
    )
    assert "Note at 02:10: slept well after a feed" in text
