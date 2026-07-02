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
