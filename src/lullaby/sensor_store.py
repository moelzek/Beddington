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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
