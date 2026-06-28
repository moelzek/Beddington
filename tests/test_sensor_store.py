from __future__ import annotations

from pathlib import Path

from lullaby.sensor_store import SensorStore


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
