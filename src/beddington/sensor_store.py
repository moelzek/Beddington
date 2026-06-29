"""Persistent, on-device history of derived sensor readings.

A tiny SQLite store (stdlib only) so the dashboard graphs show real trends over
hours/nights and survive restarts, and so a night digest can summarise the room
later. It holds only *derived numbers* (temperature, humidity, presence as 0/1,
…) — never raw audio or video — and prunes old rows so storage stays small.

One row per (timestamp, sensor key, value). Booleans are stored as 0/1 and gas
resistance in raw ohms; the display ``scale`` (ohms→kΩ) is applied on read, matching
``liveview.history_series``.
"""

from __future__ import annotations

import math
import os
import sqlite3
import threading
import time

from .liveview import DASHBOARD_SENSORS


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


class SensorStore:
    """SQLite-backed rolling history of sensor readings."""

    def __init__(self, path: str) -> None:
        self._path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS readings"
            " (ts REAL NOT NULL, key TEXT NOT NULL, value REAL NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_key_ts ON readings(key, ts)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS soothe_outcomes"
            " (ts REAL NOT NULL, sound_name TEXT NOT NULL, success INTEGER NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_soothe_outcomes_ts ON soothe_outcomes(ts)"
        )
        self._conn.commit()

    def append(
        self,
        timestamp: float,
        snapshot: dict[str, object],
        sensors: tuple[dict[str, object], ...] = DASHBOARD_SENSORS,
    ) -> None:
        rows = []
        for spec in sensors:
            value = _numeric(snapshot.get(str(spec["key"])))
            if value is not None:
                rows.append((float(timestamp), str(spec["key"]), value))
        if not rows:
            return
        with self._lock:
            self._conn.executemany("INSERT INTO readings VALUES (?, ?, ?)", rows)
            self._conn.commit()

    def series(
        self,
        since_ts: float,
        sensors: tuple[dict[str, object], ...] = DASHBOARD_SENSORS,
        max_points: int = 400,
    ) -> dict[str, object]:
        """Per-sensor time series since ``since_ts``, shaped like
        ``liveview.history_series`` (and downsampled to ``max_points``)."""
        out: dict[str, object] = {}
        with self._lock:
            for spec in sensors:
                key = str(spec["key"])
                cursor = self._conn.execute(
                    "SELECT ts, value FROM readings WHERE key=? AND ts>=? ORDER BY ts",
                    (key, float(since_ts)),
                )
                rows = cursor.fetchall()
                if max_points and len(rows) > max_points:
                    step = len(rows) // max_points
                    rows = rows[::step]
                scale = float(spec.get("scale", 1))
                out[key] = {
                    "label": spec["label"],
                    "unit": spec.get("unit", ""),
                    "bool": bool(spec.get("bool", False)),
                    "points": [[round(ts, 1), round(value * scale, 3)] for ts, value in rows],
                }
        return out

    def prune(self, older_than_ts: float) -> int:
        """Delete rows older than ``older_than_ts``. Returns rows removed."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM readings WHERE ts < ?", (float(older_than_ts),)
            )
            self._conn.commit()
            return cursor.rowcount

    def append_soothe_outcome(self, timestamp: float, sound_name: str, success: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO soothe_outcomes VALUES (?, ?, ?)",
                (float(timestamp), str(sound_name), 1 if success else 0),
            )
            self._conn.commit()

    def outcomes_since(self, since_ts: float) -> list[tuple[float, str, bool]]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT ts, sound_name, success FROM soothe_outcomes WHERE ts>=? ORDER BY ts",
                (float(since_ts),),
            )
            return [
                (float(ts), str(sound_name), bool(success))
                for ts, sound_name, success in cursor.fetchall()
            ]

    def night_aggregates(
        self,
        nights: int,
        now_ts: float | None = None,
    ) -> dict[str, list[tuple[int, int]] | list[tuple[str, int, int]]]:
        if nights < 1:
            raise ValueError("nights must be >= 1")
        now = time.time() if now_ts is None else float(now_ts)
        since_ts = now - float(nights) * 24 * 3600
        with self._lock:
            cursor = self._conn.execute(
                "SELECT ts, value FROM readings "
                "WHERE key=? AND ts>=? ORDER BY ts",
                ("motion_detected", since_ts),
            )
            motion_rows = cursor.fetchall()
            cursor = self._conn.execute(
                "SELECT sound_name, SUM(success), COUNT(*) "
                "FROM soothe_outcomes WHERE ts>=? "
                "GROUP BY sound_name ORDER BY sound_name",
                (since_ts,),
            )
            soothe_rows = cursor.fetchall()

        stir_counts: dict[int, int] = {}
        previous: float | None = None
        for ts, value in motion_rows:
            current = float(value)
            if previous is not None and current > 0.5 and previous <= 0.5:
                hour = time.localtime(float(ts)).tm_hour
                stir_counts[hour] = stir_counts.get(hour, 0) + 1
            previous = current

        return {
            "stir_hours": sorted(
                stir_counts.items(), key=lambda item: (-item[1], item[0])
            ),
            "soothe_tallies": [
                (str(sound_name), int(successes or 0), int(attempts))
                for sound_name, successes, attempts in soothe_rows
            ],
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
