from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from beddington.config import (
    AppConfig,
    DetectionConfig,
    RadarSensorConfig,
    SensorsConfig,
)
from beddington.models import AudioWindow
from beddington.pipeline import run_pipeline
from beddington.sensors import (
    Bme680AirReader,
    Mr60RadarReader,
    NullSensorReader,
    PirMotionReader,
    _coerce_radar_value,
    _radar_field_for_name,
    build_sensor_readers,
)


@dataclass
class FakeSource:
    scores: list[float]
    name: str = "fake.wav"

    @property
    def duration_seconds(self) -> float:
        return len(self.scores) * 0.5

    def windows(self) -> Iterator[AudioWindow]:
        for index in range(len(self.scores)):
            yield AudioWindow(index * 0.5, np.zeros(16_000, dtype=np.float32))


class FakeDetector:
    name = "fake detector"

    def __init__(self, scores: list[float]):
        self._scores = iter(scores)

    def score(self, samples: np.ndarray) -> float:
        del samples
        return next(self._scores)


class FakeNotifier:
    def notify(self, title: str, message: str) -> dict[str, bool]:
        assert title == "Beddington"
        assert "Sustained crying" in message
        return {"console": True, "desktop": False}


class FakeSensorReader:
    def read(self) -> dict[str, object]:
        return {
            "room_temperature_c": 21.3,
            "room_humidity_pct": 47,
            "motion_detected": True,
        }


def test_null_reader_returns_empty_sample() -> None:
    assert NullSensorReader().read() == {}


def test_build_sensor_readers_default_is_hardware_free() -> None:
    assert build_sensor_readers(SensorsConfig()) == []


def test_bme680_reader_returns_temperature_and_humidity(monkeypatch) -> None:
    calls: list[int] = []

    class FakeBmeSensor:
        data = SimpleNamespace(temperature=21.34, humidity=47.04, pressure=1012.81)

        def __init__(self, i2c_addr: int):
            calls.append(i2c_addr)

        def get_sensor_data(self) -> bool:
            return True

    monkeypatch.setitem(
        sys.modules,
        "bme680",
        SimpleNamespace(
            I2C_ADDR_PRIMARY=0x76,
            I2C_ADDR_SECONDARY=0x77,
            BME680=FakeBmeSensor,
        ),
    )

    assert Bme680AirReader(0x76).read() == {
        "room_temperature_c": 21.3,
        "room_humidity_pct": 47.0,
        "room_pressure_hpa": 1012.8,
    }
    assert calls == [0x76]


def test_bme680_reader_tries_secondary_address(monkeypatch) -> None:
    calls: list[int] = []

    class FakeBmeSensor:
        data = SimpleNamespace(temperature=20.0, humidity=50.0, pressure=1010.0)

        def __init__(self, i2c_addr: int):
            calls.append(i2c_addr)
            if i2c_addr == 0x76:
                raise OSError("primary missing")

        def get_sensor_data(self) -> bool:
            return True

    monkeypatch.setitem(
        sys.modules,
        "bme680",
        SimpleNamespace(
            I2C_ADDR_PRIMARY=0x76,
            I2C_ADDR_SECONDARY=0x77,
            BME680=FakeBmeSensor,
        ),
    )

    assert Bme680AirReader().read() == {
        "room_temperature_c": 20.0,
        "room_humidity_pct": 50.0,
        "room_pressure_hpa": 1010.0,
    }
    assert calls == [0x76, 0x77]


def test_bme680_reader_degrades_when_library_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "bme680", None)

    assert Bme680AirReader().read() == {}


def _install_fake_bme680(monkeypatch, *, gas_resistance: float, heat_stable: bool) -> list:
    configured: list[str] = []

    class FakeBmeSensor:
        data = SimpleNamespace(
            temperature=22.0,
            humidity=48.0,
            pressure=1011.0,
            gas_resistance=gas_resistance,
            heat_stable=heat_stable,
        )

        def __init__(self, i2c_addr: int):
            pass

        def set_gas_status(self, value: int) -> None:
            configured.append("status")

        def set_gas_heater_temperature(self, value: int) -> None:
            configured.append("temp")

        def set_gas_heater_duration(self, value: int) -> None:
            configured.append("duration")

        def select_gas_heater_profile(self, value: int) -> None:
            configured.append("profile")

        def get_sensor_data(self) -> bool:
            return True

    monkeypatch.setitem(
        sys.modules,
        "bme680",
        SimpleNamespace(
            I2C_ADDR_PRIMARY=0x76,
            I2C_ADDR_SECONDARY=0x77,
            BME680=FakeBmeSensor,
            ENABLE_GAS_MEAS=1,
        ),
    )
    return configured


def test_bme680_reader_includes_gas_when_enabled_and_stable(monkeypatch) -> None:
    configured = _install_fake_bme680(
        monkeypatch, gas_resistance=123456.0, heat_stable=True
    )

    reading = Bme680AirReader(0x76, include_gas=True).read()

    assert reading == {
        "room_temperature_c": 22.0,
        "room_humidity_pct": 48.0,
        "room_pressure_hpa": 1011.0,
        "room_gas_resistance_ohms": 123456,
    }
    assert configured == ["status", "temp", "duration", "profile"]


def test_bme680_reader_omits_gas_until_heat_stable(monkeypatch) -> None:
    _install_fake_bme680(monkeypatch, gas_resistance=0.0, heat_stable=False)

    reading = Bme680AirReader(0x76, include_gas=True).read()

    assert "room_gas_resistance_ohms" not in reading
    assert reading["room_temperature_c"] == 22.0


def test_bme680_reader_skips_gas_when_disabled(monkeypatch) -> None:
    configured = _install_fake_bme680(
        monkeypatch, gas_resistance=123456.0, heat_stable=True
    )

    reading = Bme680AirReader(0x76).read()

    assert "room_gas_resistance_ohms" not in reading
    assert configured == []


def test_bme680_reader_stays_available_when_data_not_ready(monkeypatch) -> None:
    class FakeBmeSensor:
        data = SimpleNamespace(temperature=22.0, humidity=48.0)

        def __init__(self, i2c_addr: int):
            pass

        def get_sensor_data(self) -> bool:
            return False

    monkeypatch.setitem(
        sys.modules,
        "bme680",
        SimpleNamespace(
            I2C_ADDR_PRIMARY=0x76,
            I2C_ADDR_SECONDARY=0x77,
            BME680=FakeBmeSensor,
        ),
    )

    reader = Bme680AirReader(0x76)
    # A not-ready cycle is skipped but must not permanently disable the sensor.
    assert reader.read() == {}
    assert reader._available is True


def test_pir_motion_reader_parses_high(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout="4: ip    pd | hi // GPIO4")

    monkeypatch.setattr("beddington.sensors.subprocess.run", fake_run)

    assert PirMotionReader(gpio_pin=4).read() == {"motion_detected": True}
    assert commands == [["pinctrl", "get", "4"]]


def test_pir_motion_reader_parses_low(monkeypatch) -> None:
    monkeypatch.setattr(
        "beddington.sensors.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="4: ip    pd | lo // GPIO4",
        ),
    )

    assert PirMotionReader(gpio_pin=4).read() == {"motion_detected": False}


def test_pir_motion_reader_degrades_when_pinctrl_missing(monkeypatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("pinctrl")

    monkeypatch.setattr("beddington.sensors.subprocess.run", fake_run)

    reader = PirMotionReader(gpio_pin=4)
    assert reader.read() == {}
    assert reader.read() == {}


def test_radar_field_routing_drops_vitals_and_keeps_context() -> None:
    # Vital-sign entities must never be routed into narration.
    assert _radar_field_for_name("Real-time respiratory rate") is None
    assert _radar_field_for_name("Real-time heart rate") is None
    # Non-medical context fields are kept.
    assert _radar_field_for_name("Person Information") == "person_present"
    assert _radar_field_for_name("Seeed MR60BHA2 Illuminance") == "room_illuminance_lx"
    assert _radar_field_for_name("Distance to detection object") == "target_distance_cm"
    assert _radar_field_for_name("Target Number") == "target_count"
    # The controllable RGB light is not a sensor we narrate.
    assert _radar_field_for_name("Seeed MR60BHA2 RGB Light") is None


def test_radar_field_routing_respects_include_flags() -> None:
    assert _radar_field_for_name("Distance to detection object", include_distance=False) is None
    assert (
        _radar_field_for_name("Target Number", include_target_count=False) is None
    )


def test_coerce_radar_value() -> None:
    assert _coerce_radar_value("person_present", True) is True
    assert _coerce_radar_value("person_present", False) is False
    assert _coerce_radar_value("target_count", 2.0) == 2
    assert _coerce_radar_value("room_illuminance_lx", 96.2106) == 96.2
    assert _coerce_radar_value("target_distance_cm", None) is None
    assert _coerce_radar_value("room_illuminance_lx", "not-a-number") is None
    # mmWave vitals report NaN with no lock — never a fabricated number.
    assert _coerce_radar_value("radar_heart_rate_bpm", float("nan")) is None
    assert _coerce_radar_value("radar_respiratory_rate", float("inf")) is None
    assert _coerce_radar_value("radar_heart_rate_bpm", 92.0) == 92.0
    # A 0 vital is the radar's "no lock" sentinel — omit it (but count 0 is valid).
    assert _coerce_radar_value("radar_heart_rate_bpm", 0.0) is None
    assert _coerce_radar_value("radar_respiratory_rate", 0.0) is None
    assert _coerce_radar_value("target_count", 0.0) == 0
    # Out-of-range vitals are a clutter/noise lock (no real person), not a
    # measurement — e.g. the buried radar's phantom "breathing ~1/min".
    assert _coerce_radar_value("radar_respiratory_rate", 1.0) is None
    assert _coerce_radar_value("radar_respiratory_rate", 16.0) == 16.0
    assert _coerce_radar_value("radar_respiratory_rate", 90.0) is None
    assert _coerce_radar_value("radar_heart_rate_bpm", 30.0) is None
    assert _coerce_radar_value("radar_heart_rate_bpm", 300.0) is None


def test_build_sensor_readers_includes_radar_when_enabled() -> None:
    readers = build_sensor_readers(
        SensorsConfig(radar=RadarSensorConfig(enabled=True, host="192.168.1.146"))
    )
    assert len(readers) == 1
    assert isinstance(readers[0], Mr60RadarReader)
    assert readers[0].host == "192.168.1.146"


def test_build_sensor_readers_skips_radar_without_host() -> None:
    assert (
        build_sensor_readers(
            SensorsConfig(radar=RadarSensorConfig(enabled=True, host=""))
        )
        == []
    )


def test_radar_field_routing_captures_vitals_only_when_enabled() -> None:
    # Off by default — vitals are dropped.
    assert _radar_field_for_name("Real-time respiratory rate") is None
    assert _radar_field_for_name("Real-time heart rate") is None
    # Explicitly enabled — captured under namespaced bench keys.
    assert (
        _radar_field_for_name("Real-time respiratory rate", include_vitals=True)
        == "radar_respiratory_rate"
    )
    assert (
        _radar_field_for_name("Real-time heart rate", include_vitals=True)
        == "radar_heart_rate_bpm"
    )


def test_build_sensor_readers_propagates_bench_vitals_flag() -> None:
    on = build_sensor_readers(
        SensorsConfig(
            radar=RadarSensorConfig(enabled=True, host="h", bench_vitals=True)
        )
    )
    assert isinstance(on[0], Mr60RadarReader)
    assert on[0].include_vitals is True

    off = build_sensor_readers(
        SensorsConfig(radar=RadarSensorConfig(enabled=True, host="h"))
    )
    assert off[0].include_vitals is False


def test_radar_reader_degrades_when_library_missing(monkeypatch) -> None:
    # With aioesphomeapi absent, the reader stays offline and never blocks.
    monkeypatch.setitem(sys.modules, "aioesphomeapi", None)
    reader = Mr60RadarReader("192.0.2.10")
    assert reader.read() == {}
    assert reader.read() == {}
    assert reader._thread is None


def test_pipeline_appends_environment_samples_without_changing_detection_events(
    tmp_path: Path,
) -> None:
    scores = [0.1, 0.8, 0.9, 0.7, 0.1, 0.1]
    started_at = datetime(2026, 6, 28, tzinfo=UTC)
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        sensors=SensorsConfig(sample_interval_seconds=1.0),
    )

    without_sensors = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=FakeNotifier(),
        config=config,
        output_dir=tmp_path / "without",
        started_at=started_at,
    )
    with_sensors = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=FakeNotifier(),
        config=config,
        output_dir=tmp_path / "with",
        started_at=started_at,
        sensor_readers=(FakeSensorReader(),),
    )

    environment_samples = [
        event for event in with_sensors.report.events if event.kind == "environment_sample"
    ]
    assert environment_samples
    assert environment_samples[0].details == {
        "room_temperature_c": 21.3,
        "room_humidity_pct": 47,
        "motion_detected": True,
    }
    assert "21.3" not in with_sensors.paths.readable_log.read_text(encoding="utf-8")
    assert "21.3" not in with_sensors.digest
    assert _detection_sequence_json(with_sensors.report.events) == (
        _detection_sequence_json(without_sensors.report.events)
    )


def _detection_sequence_json(events) -> str:
    detection_kinds = {
        "cry_started",
        "cry_ended",
        "notification_sent",
        "soothe_attempted",
        "soothe_settled",
        "soothe_quiet_check_started",
        "soothe_quiet_check",
        "soothe_quiet_confirmed",
        "soothe_unresolved",
    }
    payload = [event.to_dict() for event in events if event.kind in detection_kinds]
    return json.dumps(payload, sort_keys=True)
