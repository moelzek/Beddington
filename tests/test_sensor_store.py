from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from beddington.sensor_store import SensorStore


def _local_ts(year: int, month: int, day: int, hour: int, minute: int = 0) -> float:
    return time.mktime((year, month, day, hour, minute, 0, -1, -1, -1))


def test_store_append_and_series(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append(
        100.0,
        {"room_temperature_c": 21.0, "room_gas_resistance_ohms": 50000, "person_present": True},
    )
    store.append(
        103.0,
        {"room_temperature_c": 22.0, "room_gas_resistance_ohms": 60000, "person_present": False},
    )
    series = store.series(0.0)
    assert series["room_temperature_c"]["points"] == [[100.0, 21.0], [103.0, 22.0]]
    # gas stored in ohms, displayed in kΩ (scale applied on read)
    assert series["room_gas_resistance_ohms"]["points"] == [[100.0, 50.0], [103.0, 60.0]]
    # booleans stored as 0/1
    assert series["person_present"]["points"] == [[100.0, 1.0], [103.0, 0.0]]
    store.close()


def test_store_since_filters_by_time(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append(100.0, {"room_temperature_c": 20.0})
    store.append(200.0, {"room_temperature_c": 21.0})
    assert store.series(150.0)["room_temperature_c"]["points"] == [[200.0, 21.0]]
    store.close()


def test_store_series_downsamples_to_max_points(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    for index in range(401):
        store.append(float(index), {"room_temperature_c": float(index)})

    points = store.series(0.0, max_points=400)["room_temperature_c"]["points"]

    assert len(points) <= 400
    store.close()


def test_store_series_downsampling_keeps_latest_point(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    for index in range(11):
        store.append(float(index), {"room_temperature_c": float(index)})

    points = store.series(0.0, max_points=4)["room_temperature_c"]["points"]

    assert points[-1] == [10.0, 10.0]
    store.close()


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db = str(tmp_path / "s.db")
    first = SensorStore(db)
    first.append(10.0, {"room_temperature_c": 19.0})
    first.close()
    second = SensorStore(db)  # graphs survive a restart
    assert second.series(0.0)["room_temperature_c"]["points"] == [[10.0, 19.0]]
    second.close()


def test_store_prune_removes_old_rows(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append(100.0, {"room_temperature_c": 20.0})
    store.append(500.0, {"room_temperature_c": 21.0})
    assert store.prune(300.0) == 1
    assert store.series(0.0)["room_temperature_c"]["points"] == [[500.0, 21.0]]
    store.close()


def test_store_prune_covers_all_three_tables(tmp_path: Path) -> None:
    # Bug C: soothe_outcomes and cry_episodes must be pruned too, or they grow
    # forever and fill the Pi's SD card.
    store = SensorStore(str(tmp_path / "s.db"))
    # readings: one old, one new.
    store.append(100.0, {"room_temperature_c": 20.0})
    store.append(500.0, {"room_temperature_c": 21.0})
    # soothe_outcomes: one old, one new.
    store.append_soothe_outcome(100.0, "white-noise", True)
    store.append_soothe_outcome(500.0, "white-noise", False)
    # cry_episodes (keyed by started_ts): one old, one new.
    store.append_cry_episode(100.0, ended_ts=150.0, duration_seconds=50.0)
    store.append_cry_episode(500.0, ended_ts=560.0, duration_seconds=60.0)

    removed = store.prune(300.0)
    # One old row removed from each of the three tables.
    assert removed == 3

    # readings: only the new row survives.
    assert store.series(0.0)["room_temperature_c"]["points"] == [[500.0, 21.0]]
    # soothe_outcomes: only the new row survives.
    assert store.outcomes_since(0.0) == [(500.0, "white-noise", False)]
    # cry_episodes: only the new episode survives.
    with sqlite3.connect(str(tmp_path / "s.db")) as conn:
        started = [row[0] for row in conn.execute(
            "SELECT started_ts FROM cry_episodes ORDER BY started_ts"
        )]
    assert started == [500.0]
    store.close()


def test_store_ignores_non_numeric_and_nan(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append(1.0, {"room_temperature_c": float("nan"), "room_humidity_pct": "n/a"})
    series = store.series(0.0)
    assert series["room_temperature_c"]["points"] == []
    assert series["room_humidity_pct"]["points"] == []
    store.close()


def test_store_soothe_outcomes_roundtrip(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_soothe_outcome(100.0, "rain", True)
    store.append_soothe_outcome(200.0, "pink-noise", False, "sleep")
    assert store.outcomes_since(150.0) == [(200.0, "pink-noise", False)]
    assert store.outcomes_since(0.0) == [
        (100.0, "rain", True),
        (200.0, "pink-noise", False),
    ]
    assert store.outcomes_since_context(0.0, "sleep") == [
        (200.0, "pink-noise", False)
    ]
    assert store.outcomes_since_context(0.0, "feeding") == []
    store.close()


def test_store_migrates_old_soothe_outcomes_without_context(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE soothe_outcomes"
        " (ts REAL NOT NULL, sound_name TEXT NOT NULL, success INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO soothe_outcomes VALUES (100.0, 'rain', 1)")
    conn.commit()
    conn.close()

    store = SensorStore(str(db_path))
    store.append_soothe_outcome(200.0, "piano", False, "feeding")

    assert store.outcomes_since(0.0) == [
        (100.0, "rain", True),
        (200.0, "piano", False),
    ]
    assert store.outcomes_since_context(0.0, "") == [(100.0, "rain", True)]
    assert store.outcomes_since_context(0.0, "feeding") == [
        (200.0, "piano", False)
    ]
    store.close()


def test_store_night_aggregates_bucket_stirs_by_hour(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    now = _local_ts(2026, 1, 5, 8)

    store.append(_local_ts(2026, 1, 1, 2), {"motion_detected": False})
    store.append(_local_ts(2026, 1, 1, 2, 5), {"motion_detected": True})
    store.append(_local_ts(2026, 1, 3, 2), {"motion_detected": False})
    store.append(_local_ts(2026, 1, 3, 2, 5), {"motion_detected": True})
    store.append(_local_ts(2026, 1, 3, 2, 10), {"motion_detected": True})
    store.append(_local_ts(2026, 1, 4, 4), {"motion_detected": False})
    store.append(_local_ts(2026, 1, 4, 4, 5), {"motion_detected": True})
    store.append(_local_ts(2026, 1, 4, 4, 10), {"motion_detected": False})
    store.append(_local_ts(2026, 1, 4, 2), {"motion_detected": False})
    store.append(_local_ts(2026, 1, 4, 2, 5), {"motion_detected": True})

    assert store.night_aggregates(3, now_ts=now)["stir_hours"] == [(2, 2), (4, 1)]
    store.close()


def test_store_night_aggregates_tallies_recent_soothe_outcomes(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    now = _local_ts(2026, 1, 5, 8)

    store.append_soothe_outcome(_local_ts(2026, 1, 1, 21), "rain", True)
    store.append_soothe_outcome(_local_ts(2026, 1, 3, 21), "rain", True)
    store.append_soothe_outcome(_local_ts(2026, 1, 3, 22), "rain", False)
    store.append_soothe_outcome(_local_ts(2026, 1, 4, 21), "waves", False)
    store.append_soothe_outcome(_local_ts(2026, 1, 4, 22), "waves", True)

    assert store.night_aggregates(3, now_ts=now)["soothe_tallies"] == [
        ("rain", 1, 2),
        ("waves", 1, 2),
    ]
    store.close()


def test_store_events_point_and_episode_roundtrip(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    row = store.append_event("stirring", 100.0)
    assert isinstance(row, int)
    store.append_event("manual_note", 150.0, ended_ts=150.0, detail="gave a feed")
    store.close_event(row, 130.0)

    timeline = store.timeline_since(0.0)
    assert [(e["kind"], e["started_ts"], e["ended_ts"]) for e in timeline] == [
        ("stirring", 100.0, 130.0),
        ("manual_note", 150.0, 150.0),
    ]
    assert timeline[1]["detail"] == "gave a feed"
    store.close()


def test_store_timeline_merges_cry_episodes_chronologically(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_event("sound_played", 200.0, ended_ts=200.0, detail="rain")
    store.append_cry_episode(100.0, ended_ts=140.0)
    store.append_cry_episode(300.0, duration_seconds=60.0)  # no ended_ts stored
    store.append_cry_episode(400.0)  # open cry

    timeline = store.timeline_since(0.0)
    assert [e["kind"] for e in timeline] == [
        "crying", "sound_played", "crying", "crying",
    ]
    assert timeline[0]["ended_ts"] == 140.0
    assert timeline[2]["ended_ts"] == 360.0  # started + duration
    assert timeline[3]["ended_ts"] == 400.0  # terminal start-only row
    store.close()


def test_cry_episode_count_since_includes_tracker_events(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_cry_episode(100.0)
    store.append_cry_episode(300.0)
    store.append_event("crying", 150.0, ended_ts=170.0)
    store.append_event("crying", 180.0, ended_ts=220.0)
    store.append_event("crying", 400.0, ended_ts=430.0)
    store.append_event("stirring", 500.0, ended_ts=520.0)

    assert store.cry_episode_count_since(200.0) == 3
    assert store.cry_episode_count_since(0.0) == 5
    store.close()


def test_store_timeline_window_keeps_open_and_overlapping(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_event("room_warm", 10.0, ended_ts=20.0)  # fully before window
    row = store.append_event("caregiver_present", 30.0)  # open, started before
    store.append_event("stirring", 50.0, ended_ts=120.0)  # ends inside window
    assert row is not None

    timeline = store.timeline_since(100.0)
    assert [e["kind"] for e in timeline] == ["caregiver_present", "stirring"]
    store.close()


def test_store_prune_keeps_open_events(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_event("stirring", 10.0, ended_ts=20.0)
    open_row = store.append_event("caregiver_present", 15.0)
    removed = store.prune(100.0)
    assert removed == 1
    timeline = store.timeline_since(0.0)
    assert [e["kind"] for e in timeline] == ["caregiver_present"]
    assert open_row is not None
    store.close()


def test_store_close_stale_events_recovers_from_crash(tmp_path: Path) -> None:
    path = str(tmp_path / "s.db")
    store = SensorStore(path)
    store.append_event("stirring", 100.0)  # never closed: simulated crash
    store.append_event("manual_note", 110.0, ended_ts=110.0, detail="note")
    store.close()

    reopened = SensorStore(path)
    assert reopened.close_stale_events() == 1
    timeline = reopened.timeline_since(0.0)
    assert all(e["ended_ts"] is not None for e in timeline)
    stirring = [e for e in timeline if e["kind"] == "stirring"][0]
    assert stirring["ended_ts"] == 100.0  # closed at its start: all we know
    reopened.close()


def test_store_close_event_never_ends_before_start(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    row = store.append_event("stirring", 100.0)
    store.close_event(row, 40.0)
    assert store.timeline_since(0.0)[0]["ended_ts"] == 100.0
    store.close()


def test_store_close_event_ignores_double_close(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    row = store.append_event("stirring", 100.0)
    store.close_event(row, 130.0)
    store.close_event(row, 500.0)  # a late/racing second close is a no-op
    assert store.timeline_since(0.0)[0]["ended_ts"] == 130.0
    store.close()


def test_store_timeline_terminal_open_cry_is_not_billed_to_now(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "s.db"))
    store.append_cry_episode(100.0)  # monitor exited mid-cry: start only
    row = store.timeline_since(0.0)[0]
    assert row["kind"] == "crying"
    assert row["ended_ts"] == 100.0  # all we know is that it began
    store.close()
