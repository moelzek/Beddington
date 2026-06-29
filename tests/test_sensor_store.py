from __future__ import annotations

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
    store.append_soothe_outcome(200.0, "pink-noise", False)
    assert store.outcomes_since(150.0) == [(200.0, "pink-noise", False)]
    assert store.outcomes_since(0.0) == [
        (100.0, "rain", True),
        (200.0, "pink-noise", False),
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
