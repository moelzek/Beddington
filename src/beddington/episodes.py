"""Derive parent-friendly episodes from the live sensor snapshots.

Turns the raw per-tick readings the live-view sampler already collects into a
small stream of *derived* events — "stirring", "someone in the room", "the room
ran warm", "a sensor dropped out", "the camera could not see the cot" — so the
event history (SensorStore ``events`` table) can answer "what happened last
night?". Pure and deterministic: no I/O, no threads, no raw audio or video —
only booleans and numbers that were already derived.

Each condition uses a dwell and/or hysteresis so episodes do not flap on a
single noisy tick. The tracker reports changes; persisting them is the
caller's job (``cli._SensorSampler``).

Honest naming caveat: ``baby_not_visible`` is derived purely from camera frame
*staleness* (frames stopped arriving) — it makes no visibility inference, so a
live stream with the baby out of frame never triggers it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Only these keys are watched for sensor_unavailable episodes. Radar keys
# (target_distance_cm, target_count, radar_* vitals) are intermittent BY
# DESIGN — the reader pops them whenever nobody is in range — so a healthy
# empty room must not read as a sensor outage.
_AVAILABILITY_KEYS = frozenset(
    {
        "room_temperature_c",
        "room_humidity_pct",
        "room_pressure_hpa",
        "room_gas_resistance_ohms",
        "room_illuminance_lx",
        "motion_detected",
        "person_present",
    }
)


@dataclass(frozen=True)
class EpisodeThresholds:
    """Dwell/hysteresis knobs for episode detection.

    ``camera_stale_s`` is deliberately much coarser than the live snapshot's
    ``max_camera_frame_age_s`` (8s): the dashboard flags a stale frame quickly,
    but an *episode* is only worth remembering after a sustained outage.
    """

    warm_c: float = 24.0
    cold_c: float = 16.0
    temp_hysteresis_c: float = 0.5
    temp_dwell_s: float = 300.0
    stir_gap_s: float = 120.0
    presence_open_s: float = 10.0
    presence_close_s: float = 30.0
    camera_stale_s: float = 30.0
    sensor_missing_s: float = 60.0


@dataclass(frozen=True)
class EpisodeChange:
    """One episode boundary: ``action`` is "start" or "end"."""

    action: str
    kind: str
    ts: float
    detail: str = ""


def _flag(snapshot: dict[str, object], key: str) -> bool | None:
    value = snapshot.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0.5
    return None


def _number(snapshot: dict[str, object], key: str) -> float | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass
class _Dwell:
    """Tracks how long a condition has been continuously true."""

    since: float | None = None

    def update(self, ts: float, active: bool) -> float:
        """Returns seconds the condition has held (0 when inactive)."""
        if not active:
            self.since = None
            return 0.0
        if self.since is None:
            self.since = ts
        return ts - self.since


@dataclass
class EpisodeTracker:
    """Feeds on (timestamp, snapshot) ticks; emits EpisodeChange boundaries."""

    thresholds: EpisodeThresholds = field(default_factory=EpisodeThresholds)

    def __post_init__(self) -> None:
        # (kind, detail) -> started_ts for episodes currently open.
        self._open: dict[tuple[str, str], float] = {}
        self._last_motion_true: float | None = None
        self._presence_true = _Dwell()
        self._presence_false = _Dwell()
        self._warm = _Dwell()
        self._cold = _Dwell()
        self._seen_keys: set[str] = set()
        self._missing: dict[str, _Dwell] = {}

    def open_episodes(self) -> dict[tuple[str, str], float]:
        return dict(self._open)

    def update(
        self,
        ts: float,
        snapshot: dict[str, object],
        camera_frame_age_s: float | None = None,
    ) -> list[EpisodeChange]:
        changes: list[EpisodeChange] = []
        self._update_stirring(ts, snapshot, changes)
        self._update_presence(ts, snapshot, changes)
        self._update_temperature(ts, snapshot, changes)
        self._update_sensor_availability(ts, snapshot, changes)
        self._update_camera(ts, camera_frame_age_s, changes)
        return changes

    def flush(self, now: float) -> list[EpisodeChange]:
        """Close every open episode (sampler shutdown)."""
        changes = [
            EpisodeChange("end", kind, now, detail)
            for (kind, detail) in sorted(self._open)
        ]
        self._open.clear()
        return changes

    def _start(
        self,
        changes: list[EpisodeChange],
        kind: str,
        ts: float,
        detail: str = "",
    ) -> None:
        key = (kind, detail)
        if key not in self._open:
            self._open[key] = ts
            changes.append(EpisodeChange("start", kind, ts, detail))

    def _end(
        self,
        changes: list[EpisodeChange],
        kind: str,
        ts: float,
        detail: str = "",
    ) -> None:
        started = self._open.pop((kind, detail), None)
        if started is not None:
            changes.append(EpisodeChange("end", kind, max(ts, started), detail))

    def _update_stirring(
        self,
        ts: float,
        snapshot: dict[str, object],
        changes: list[EpisodeChange],
    ) -> None:
        motion = _flag(snapshot, "motion_detected")
        if motion:
            self._last_motion_true = ts
            self._start(changes, "stirring", ts)
        elif ("stirring", "") in self._open and self._last_motion_true is not None:
            if ts - self._last_motion_true >= self.thresholds.stir_gap_s:
                # Close at the last movement actually seen, not at the gap end.
                self._end(changes, "stirring", self._last_motion_true)

    def _update_presence(
        self,
        ts: float,
        snapshot: dict[str, object],
        changes: list[EpisodeChange],
    ) -> None:
        present = _flag(snapshot, "person_present")
        if present is None:
            # No reading this tick: hold state, do not open or close on silence.
            return
        held_true = self._presence_true.update(ts, present)
        held_false = self._presence_false.update(ts, not present)
        if present and held_true >= self.thresholds.presence_open_s:
            start = ts if self._presence_true.since is None else self._presence_true.since
            self._start(changes, "caregiver_present", start)
        elif not present and held_false >= self.thresholds.presence_close_s:
            end = ts if self._presence_false.since is None else self._presence_false.since
            self._end(changes, "caregiver_present", end)

    def _update_temperature(
        self,
        ts: float,
        snapshot: dict[str, object],
        changes: list[EpisodeChange],
    ) -> None:
        temp = _number(snapshot, "room_temperature_c")
        if temp is None:
            return
        t = self.thresholds
        held_warm = self._warm.update(ts, temp >= t.warm_c)
        held_cold = self._cold.update(ts, temp <= t.cold_c)
        if held_warm >= t.temp_dwell_s:
            start = ts if self._warm.since is None else self._warm.since
            self._start(changes, "room_warm", start)
        elif temp < t.warm_c - t.temp_hysteresis_c:
            self._end(changes, "room_warm", ts)
        if held_cold >= t.temp_dwell_s:
            start = ts if self._cold.since is None else self._cold.since
            self._start(changes, "room_cold", start)
        elif temp > t.cold_c + t.temp_hysteresis_c:
            self._end(changes, "room_cold", ts)

    def _update_sensor_availability(
        self,
        ts: float,
        snapshot: dict[str, object],
        changes: list[EpisodeChange],
    ) -> None:
        self._seen_keys.update(key for key in snapshot if key in _AVAILABILITY_KEYS)
        for key in sorted(self._seen_keys):
            dwell = self._missing.setdefault(key, _Dwell())
            held = dwell.update(ts, key not in snapshot)
            if key in snapshot:
                self._end(changes, "sensor_unavailable", ts, detail=key)
            elif held >= self.thresholds.sensor_missing_s:
                start = ts if dwell.since is None else dwell.since
                self._start(changes, "sensor_unavailable", start, detail=key)

    def _update_camera(
        self,
        ts: float,
        camera_frame_age_s: float | None,
        changes: list[EpisodeChange],
    ) -> None:
        if camera_frame_age_s is None:
            # No camera wired (or broker not up yet): unknown, not "not visible".
            return
        if camera_frame_age_s >= self.thresholds.camera_stale_s:
            # Frames stopped arriving camera_frame_age_s ago.
            self._start(changes, "baby_not_visible", ts - camera_frame_age_s)
        else:
            self._end(changes, "baby_not_visible", ts - max(0.0, camera_frame_age_s))
