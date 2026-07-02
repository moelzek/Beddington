"""A deterministic night summary built from the persisted sensor history.

Turns the per-sensor time series (from ``SensorStore.series`` / the dashboard's
``/history.json``) into a short, plain-English recap of the room overnight:
temperature range and comfort, humidity, air, lighting, how much someone was
nearby, and how settled the movement was.

Honest by construction: it states only what the sensors recorded, labels the
movement read as a best guess, makes NO medical or safety claim (no asleep / safe
/ healthy / breathing-as-a-vital wording), and frames any radar breathing/heart
data as a rough bench reading. It is deterministic — no LLM — so it can never
fabricate. An optional LLM polish lives behind a flag in the CLI, never here.
"""

from __future__ import annotations

import time
import re
from collections.abc import Callable, Mapping

from .assistant import _air_label, _bright_label, _humid_label, _temp_label
from .child_profile import CHILD_NAME

_TREND_MIN_COUNT = 2
_BANNED_WORDS = {
    "asleep",
    "sleeping",
    "slept",
    "safe",
    "healthy",
    "fine",
    "normal",
    "well",
    "breathing",
}


def _points(series: dict[str, object], key: str) -> list[list[float]]:
    entry = series.get(key)
    if isinstance(entry, dict):
        points = entry.get("points")
        if isinstance(points, list):
            return points
    return []


def _values(series: dict[str, object], key: str) -> list[float]:
    return [p[1] for p in _points(series, key)]


def _hour_label(hour: int) -> str:
    hour = hour % 24
    suffix = "am" if hour < 12 else "pm"
    hour_12 = hour % 12 or 12
    return f"~{hour_12}{suffix}"


def _sound_label(sound_name: object) -> str | None:
    label = str(sound_name).replace("_", " ").replace("-", " ")
    label = " ".join(label.split())
    if not label:
        return None
    words = set(re.findall(r"[a-z]+", label.lower()))
    if words & _BANNED_WORDS:
        return None
    return label


def _trend_lines(aggregates: Mapping[str, object] | None) -> list[str]:
    if aggregates is None:
        return []

    lines: list[str] = []
    stir_hours = aggregates.get("stir_hours")
    if isinstance(stir_hours, list):
        hours: list[tuple[int, int]] = []
        for row in stir_hours:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                hour = int(row[0])
                count = int(row[1])
            except (TypeError, ValueError):
                continue
            if count >= _TREND_MIN_COUNT:
                hours.append((hour, count))
        if hours:
            hour, _count = min(hours, key=lambda item: (-item[1], item[0]))
            lines.append(
                f"• {CHILD_NAME} usually stirs around {_hour_label(hour)} "
                "(best guess)."
            )

    soothe_tallies = aggregates.get("soothe_tallies")
    if isinstance(soothe_tallies, list):
        tallies: list[tuple[str, int, int]] = []
        for row in soothe_tallies:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            label = _sound_label(row[0])
            if label is None:
                continue
            try:
                successes = int(row[1])
                attempts = int(row[2])
            except (TypeError, ValueError):
                continue
            if attempts >= _TREND_MIN_COUNT and 0 <= successes <= attempts:
                tallies.append((label, successes, attempts))
        if tallies:
            label, successes, attempts = min(
                tallies,
                key=lambda item: (-(item[1] / item[2]), -item[2], item[0].lower()),
            )
            lines.append(
                f"• When {label} played, {CHILD_NAME} quieted {successes}/{attempts} times "
                "(best guess)."
            )

    return lines


def summarise_night(
    series: dict[str, object],
    time_label: Callable[[float], str] | None = None,
    aggregates: Mapping[str, object] | None = None,
) -> str:
    """Plain-English recap of the room from a per-sensor time series."""
    if time_label is None:
        time_label = lambda ts: time.strftime("%H:%M", time.localtime(ts))  # noqa: E731

    trend_lines = _trend_lines(aggregates)
    all_ts = [p[0] for key in series for p in _points(series, key)]
    if not all_ts:
        if trend_lines:
            return "\n".join(["Here's the recent pattern:"] + trend_lines)
        return "I don't have enough history yet for a night summary."

    span_hours = (max(all_ts) - min(all_ts)) / 3600
    if span_hours >= 1:
        unit = "hour" if round(span_hours) == 1 else "hours"
        lines = [f"Here's the room over the last {span_hours:.0f} {unit}:"]
    else:
        lines = ["Here's the room so far:"]

    temp = _points(series, "room_temperature_c")
    if temp:
        vals = [p[1] for p in temp]
        low, high, avg = min(vals), max(vals), sum(vals) / len(vals)
        coolest = min(temp, key=lambda p: p[1])[0]
        extra = f", coolest around {time_label(coolest)}" if high - low >= 1 else ""
        lines.append(f"• Temperature {low:.0f} to {high:.0f}°C, {_temp_label(avg)}{extra}.")

    humidity = _values(series, "room_humidity_pct")
    if humidity:
        low, high = min(humidity), max(humidity)
        avg = sum(humidity) / len(humidity)
        lines.append(f"• Humidity {low:.0f} to {high:.0f}%, {_humid_label(avg)}.")

    gas = _values(series, "room_gas_resistance_ohms")  # stored in kilo-ohms
    if gas:
        avg = sum(gas) / len(gas)
        lines.append(f"• Air {_air_label(avg * 1000)}.")

    lux = _values(series, "room_illuminance_lx")
    if lux:
        avg = sum(lux) / len(lux)
        lines.append(f"• Lighting mostly {_bright_label(avg)}.")

    present = _values(series, "person_present")
    if present:
        pct = round(100 * sum(present) / len(present))
        if pct >= 80:
            lines.append("• Someone was nearby almost the whole time.")
        elif pct >= 20:
            lines.append(f"• Someone was nearby about {pct}% of the time.")
        else:
            lines.append("• The room was mostly empty.")

    motion = _points(series, "motion_detected")
    if motion:
        stirs = sum(
            1
            for i in range(1, len(motion))
            if motion[i][1] > 0.5 and motion[i - 1][1] <= 0.5
        )
        if stirs == 0:
            phrase = "settled — no movement picked up"
        elif stirs <= 4:
            plural = "s" if stirs != 1 else ""
            phrase = f"mostly settled — {stirs} spell{plural} of movement"
        else:
            phrase = f"fairly restless — {stirs} spells of movement"
        lines.append(f"• Movement: {phrase} (best guess).")

    lines.extend(trend_lines)

    if _values(series, "radar_respiratory_rate") or _values(series, "radar_heart_rate_bpm"):
        lines.append(
            "• The radar logged some breathing and heart-rate estimates when "
            "someone was close and still — rough bench readings."
        )

    return "\n".join(lines)
