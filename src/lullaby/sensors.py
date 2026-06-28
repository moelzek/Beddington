from __future__ import annotations

import re
import subprocess
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


def build_sensor_readers(sensors_config: SensorsConfig) -> list[SensorReader]:
    readers: list[SensorReader] = []
    if sensors_config.air.enabled:
        readers.append(Bme680AirReader(sensors_config.air.i2c_address))
    if sensors_config.motion.enabled:
        readers.append(PirMotionReader(sensors_config.motion.gpio_pin))
    return readers


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
