from __future__ import annotations

import asyncio
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
    def __init__(self, i2c_address: int = 0x76):
        self.i2c_address = i2c_address
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
                self._available = False
                return {}
            return {
                "room_temperature_c": round(float(sensor.data.temperature), 1),
                "room_humidity_pct": round(float(sensor.data.humidity), 1),
            }
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
                self._sensor = bme680.BME680(i2c_addr=address)
                return self._sensor
            except Exception:
                continue
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


# mmWave entities whose names match any of these are deliberately never routed,
# so the radar's vital signs (respiratory/heart rate) can never reach the
# narration. They stay bench-only — no medical or vital-sign claims.
_RADAR_VITAL_HINTS = ("respirat", "heart", "breath", "pulse")


class Mr60RadarReader:
    """Reads presence and room context from a Seeed MR60BHA2 mmWave kit over the
    ESPHome native API.

    A background thread keeps a live connection and updates a cached snapshot, so
    ``read()`` is always non-blocking and never perturbs the detection loop. Only
    non-medical fields are routed (presence, room brightness, target distance and
    count); respiratory- and heart-rate entities are deliberately dropped.
    """

    def __init__(
        self,
        host: str,
        port: int = 6053,
        password: str = "",
        include_distance: bool = True,
        include_target_count: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.include_distance = include_distance
        self.include_target_count = include_target_count
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
            )
            if field is not None:
                routing[key] = field

        def on_state(state: Any) -> None:
            field = routing.get(getattr(state, "key", None))
            if field is None:
                return
            value = _coerce_radar_value(field, getattr(state, "state", None))
            if value is None:
                return
            with self._lock:
                self._latest[field] = value

        client.subscribe_states(on_state)
        while True:
            await asyncio.sleep(3600)


def build_sensor_readers(sensors_config: SensorsConfig) -> list[SensorReader]:
    readers: list[SensorReader] = []
    if sensors_config.air.enabled:
        readers.append(Bme680AirReader(sensors_config.air.i2c_address))
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
            )
        )
    return readers


def _radar_field_for_name(
    name: str,
    include_distance: bool = True,
    include_target_count: bool = True,
) -> str | None:
    lowered = name.lower()
    if any(hint in lowered for hint in _RADAR_VITAL_HINTS):
        return None
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
    if field == "target_count":
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


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
