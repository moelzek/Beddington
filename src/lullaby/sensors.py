from __future__ import annotations

import asyncio
import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .config import SensorsConfig


class SensorReader(Protocol):
    def read(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class NullSensorReader:
    def read(self) -> dict[str, object]:
        return {}


class Bme680AirReader:
    def __init__(self, i2c_address: int = 0x76, include_gas: bool = False):
        self.i2c_address = i2c_address
        self.include_gas = include_gas
        self._sensor: Any | None = None
        self._available = True

    def read(self) -> dict[str, object]:
        if not self._available:
            return {}

        try:
            sensor = self._sensor or self._open_sensor()
            if sensor is None:
                return {}
            if not sensor.get_sensor_data():
                # No fresh data this cycle (common while the gas heater runs).
                # Skip this read but keep the sensor available for the next one.
                return {}
            reading: dict[str, object] = {
                "room_temperature_c": round(float(sensor.data.temperature), 1),
                "room_humidity_pct": round(float(sensor.data.humidity), 1),
                "room_pressure_hpa": round(float(sensor.data.pressure), 1),
            }
            # Gas resistance is only valid once the heater is warmed up. Read it
            # defensively so a gas hiccup can never drop temperature/humidity.
            if self.include_gas:
                try:
                    if getattr(sensor.data, "heat_stable", False):
                        gas = sensor.data.gas_resistance
                        if gas is not None:
                            reading["room_gas_resistance_ohms"] = int(gas)
                except Exception:
                    pass
            return reading
        except Exception:
            self._available = False
            return {}

    def _open_sensor(self) -> Any | None:
        try:
            import bme680
        except Exception:
            self._available = False
            return None

        addresses = _candidate_i2c_addresses(
            self.i2c_address,
            int(getattr(bme680, "I2C_ADDR_PRIMARY", 0x76)),
            int(getattr(bme680, "I2C_ADDR_SECONDARY", 0x77)),
        )
        for address in addresses:
            try:
                sensor = bme680.BME680(i2c_addr=address)
            except Exception:
                continue
            if self.include_gas:
                _enable_bme680_gas(sensor, bme680)
            self._sensor = sensor
            return self._sensor
        self._available = False
        return None


@dataclass
class PirMotionReader:
    gpio_pin: int = 4
    timeout_seconds: float = 1.0
    _available: bool = True

    def read(self) -> dict[str, object]:
        if not self._available:
            return {}
        try:
            result = subprocess.run(
                ["pinctrl", "get", str(self.gpio_pin)],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            self._available = False
            return {}

        if result.returncode != 0:
            self._available = False
            return {}

        value = _parse_pinctrl_level(result.stdout)
        if value is None:
            return {}
        return {"motion_detected": value}


# The radar's vital-sign entities (respiratory/heart rate) are routed ONLY when
# bench_vitals is explicitly enabled, under their own namespaced keys. They are
# never fed into the product narration (the narrator excludes and bans them) and
# are surfaced only as clearly-labelled raw bench data — no medical or vital-sign
# claims, never a product safety signal.
RADAR_RESPIRATORY_KEY = "radar_respiratory_rate"
RADAR_HEART_RATE_KEY = "radar_heart_rate_bpm"


class Mr60RadarReader:
    """Reads presence and room context from a Seeed MR60BHA2 mmWave kit over the
    ESPHome native API.

    A background thread keeps a live connection and updates a cached snapshot, so
    ``read()`` is always non-blocking and never perturbs the detection loop. By
    default only non-medical fields are routed (presence, room brightness, target
    distance and count); respiratory- and heart-rate entities are dropped unless
    ``include_vitals`` is explicitly set, in which case they are captured under
    their own namespaced keys as raw bench data (never fed to the narration).
    """

    def __init__(
        self,
        host: str,
        port: int = 6053,
        password: str = "",
        include_distance: bool = True,
        include_target_count: bool = True,
        include_vitals: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.include_distance = include_distance
        self.include_target_count = include_target_count
        self.include_vitals = include_vitals
        self._latest: dict[str, object] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._available = True

    def read(self) -> dict[str, object]:
        if not self._available:
            return {}
        if not self._started:
            self._start()
        with self._lock:
            return dict(self._latest)

    def _start(self) -> None:
        self._started = True
        try:
            import aioesphomeapi  # noqa: F401
        except Exception:
            self._available = False
            return
        self._thread = threading.Thread(
            target=self._run,
            name="lullaby-radar",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        # Reconnect with backoff so a slow first connect or a dropped WiFi link
        # self-heals. read() keeps returning the last cached snapshot meanwhile,
        # so the detection loop is never blocked or perturbed.
        backoff = 1.0
        while True:
            try:
                asyncio.run(self._stream())
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _stream(self) -> None:
        from aioesphomeapi import APIClient

        client = APIClient(self.host, self.port, self.password)
        await client.connect(login=True)
        entities, _ = await client.list_entities_services()
        routing: dict[Any, str] = {}
        for entity in entities:
            key = getattr(entity, "key", None)
            if key is None:
                continue
            field = _radar_field_for_name(
                str(getattr(entity, "name", "")),
                self.include_distance,
                self.include_target_count,
                self.include_vitals,
            )
            if field is not None:
                routing[key] = field

        def on_state(state: Any) -> None:
            field = routing.get(getattr(state, "key", None))
            if field is None:
                return
            value = _coerce_radar_value(field, getattr(state, "state", None))
            with self._lock:
                if value is None:
                    # No valid reading (e.g. a vital with no lock reports NaN) —
                    # drop any stale value rather than keep showing it.
                    self._latest.pop(field, None)
                else:
                    self._latest[field] = value

        client.subscribe_states(on_state)
        while True:
            await asyncio.sleep(3600)


def build_sensor_readers(sensors_config: SensorsConfig) -> list[SensorReader]:
    readers: list[SensorReader] = []
    if sensors_config.air.enabled:
        readers.append(
            Bme680AirReader(sensors_config.air.i2c_address, sensors_config.air.gas)
        )
    if sensors_config.motion.enabled:
        readers.append(PirMotionReader(sensors_config.motion.gpio_pin))
    if sensors_config.radar.enabled and sensors_config.radar.host:
        readers.append(
            Mr60RadarReader(
                sensors_config.radar.host,
                sensors_config.radar.port,
                sensors_config.radar.password,
                sensors_config.radar.include_distance,
                sensors_config.radar.include_target_count,
                sensors_config.radar.bench_vitals,
            )
        )
    return readers


def _radar_field_for_name(
    name: str,
    include_distance: bool = True,
    include_target_count: bool = True,
    include_vitals: bool = False,
) -> str | None:
    lowered = name.lower()
    # Vital signs are routed only when bench_vitals is on; otherwise dropped so
    # they can never reach the product narration.
    if "respirat" in lowered or "breath" in lowered:
        return RADAR_RESPIRATORY_KEY if include_vitals else None
    if "heart" in lowered or "pulse" in lowered:
        return RADAR_HEART_RATE_KEY if include_vitals else None
    if "person" in lowered or "presence" in lowered:
        return "person_present"
    if "illuminance" in lowered:
        return "room_illuminance_lx"
    if include_distance and "distance" in lowered:
        return "target_distance_cm"
    if include_target_count and "target number" in lowered:
        return "target_count"
    return None


def _coerce_radar_value(field: str, value: object) -> object | None:
    if value is None:
        return None
    if field == "person_present":
        return bool(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        # mmWave vitals report NaN when there is no lock (subject not still/close
        # enough). Treat that as "no reading", never a fabricated value.
        return None
    if field == "target_count":
        return int(round(number))
    rounded = round(number, 1)
    if field in (RADAR_RESPIRATORY_KEY, RADAR_HEART_RATE_KEY) and rounded <= 0:
        # A 0 (or negative) breathing/heart rate is the radar's "no lock"
        # sentinel, not a real measurement — omit it like NaN.
        return None
    return rounded


def _enable_bme680_gas(sensor: Any, bme680: Any) -> None:
    try:
        sensor.set_gas_status(getattr(bme680, "ENABLE_GAS_MEAS", 1))
        sensor.set_gas_heater_temperature(320)
        sensor.set_gas_heater_duration(150)
        sensor.select_gas_heater_profile(0)
    except Exception:
        # Gas is optional; temperature/humidity still work without it.
        pass


def _candidate_i2c_addresses(
    configured: int,
    primary: int,
    secondary: int,
) -> tuple[int, ...]:
    addresses: list[int] = []
    for address in (configured, primary, secondary):
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def _parse_pinctrl_level(output: str) -> bool | None:
    match = re.search(r"\|\s*(hi|lo)\b", output, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).lower() == "hi"
