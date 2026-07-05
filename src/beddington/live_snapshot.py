"""Fused live-view state contract.

The engine is intentionally deterministic: callers pass ``now`` and all input
snapshots, and the module does no I/O. ``arousal_score`` is an uncalibrated
0..1 display score: crying = clamp(max(0.85, cry_score)), wiggling =
min(0.5 + 0.1 * motion transitions, 0.8), calm = 0.25, sleeping = 0.1, and
missing/uncertain/device-fault states are null.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

History = list[tuple[float, dict[str, object]]]

STATE_ACTIONS = {"crying": ("comfort_now", "Comfort now"), "sensor_unreliable": ("reposition_device", "Check the device"), "wiggling": ("check_camera", "Check the camera"), "uncertain": ("check_camera", "Check the camera")}
ROOM_KEYS = {"temperature_c": ("room_temperature_c", "°C"), "humidity_pct": ("room_humidity_pct", "%"), "pressure_hpa": ("room_pressure_hpa", "hPa"), "gas_kohm": ("room_gas_resistance_ohms", "kΩ"), "illuminance_lx": ("room_illuminance_lx", "lx")}
RADAR_KEYS = ("person_present", "motion_detected", "target_distance_cm", "target_count", "radar_respiratory_rate", "radar_heart_rate_bpm")


@dataclass(frozen=True)
class SnapshotThresholds:
    max_reading_age_s: float = 12.0
    max_camera_frame_age_s: float = 8.0
    max_radar_age_s: float = 12.0
    health_bad_checks_to_enter: int = 2
    health_recovered_checks_to_exit: int = 3
    state_min_dwell_s: float = 20.0
    cry_clear_grace_s: float = 30.0
    presence_false_dwell_s: float = 10.0
    motion_window_s: float = 300.0
    motion_active_min_s: float = 3.0
    wiggling_release_s: float = 120.0
    still_min_s: float = 1200.0
    still_exit_motion_s: float = 3.0
    quiet_window_s: float = 900.0
    quiet_max_motion_transitions: int = 2
    room_cold_below_c: float = 16.0
    room_warm_above_c: float = 20.0
    room_temp_hysteresis_c: float = 0.5
    caregiver_min_targets: int = 2
    caregiver_dwell_s: float = 5.0
    caregiver_release_s: float = 30.0
    t2_repeat_cooldown_s: float = 600.0
    device_restart_notice_s: float = 120.0
    max_evidence_items: int = 8


@dataclass
class PresenceInfo:
    value: bool | None
    corroborated: bool
    age_s: float | None
    status: str
    note: str
    false_streak_s: float | None
    target_count: int | None
    target_distance_cm: float | None


@dataclass
class MotionInfo:
    value: bool | None
    age_s: float | None
    status: str
    transitions_window: int
    quiet_transitions: int
    last_transition_ts: float | None
    last_true_ts: float | None
    still_for_s: float | None


@dataclass
class CaregiverInfo:
    active: bool
    target_count: int | None
    age_s: float | None
    sustained_s: float | None
    held: bool


@dataclass
class _T2AlertState:
    seq: int
    raised_ts: float


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(max(0.0, float(value)), 1)


def latest_value_age(history: History, key: str, now: float) -> tuple[object | None, float | None]:
    for ts, snapshot in reversed(history):
        if key in snapshot:
            return snapshot.get(key), max(0.0, now - float(ts))
    return None, None


def signal_status(age_s: float | None, max_age_s: float) -> str:
    if age_s is None:
        return "missing"
    return "fresh" if age_s <= max_age_s else "stale"


def _last_sample_age(history: History, now: float) -> float | None:
    return max(0.0, now - float(history[-1][0])) if history else None


def _last_any_key_age(history: History, keys: tuple[str, ...], now: float) -> float | None:
    for ts, snapshot in reversed(history):
        if any(key in snapshot for key in keys):
            return max(0.0, now - float(ts))
    return None


def _bool_samples(history: History, key: str) -> list[tuple[float, bool]]:
    return [(float(ts), bool(snapshot[key])) for ts, snapshot in history if isinstance(snapshot.get(key), bool)]


def motion_transitions(history: History, now: float, window_s: float) -> tuple[int, float | None]:
    start = now - window_s
    last: bool | None = None
    count = 0
    last_ts: float | None = None
    for ts, value in _bool_samples(history, "motion_detected"):
        if ts > now:
            continue
        if ts >= start and value and last is False:
            count += 1
            last_ts = ts
        last = value
    return count, last_ts


def last_true_motion_ts(history: History, now: float) -> float | None:
    for ts, value in reversed(_bool_samples(history, "motion_detected")):
        if ts <= now and value:
            return ts
    return None


def stillness_duration(history: History, now: float) -> float | None:
    samples = [(ts, value) for ts, value in _bool_samples(history, "motion_detected") if ts <= now]
    if not samples:
        return None
    if samples[-1][1]:
        return 0.0
    last_on = next((ts for ts, value in reversed(samples) if value), None)
    start = last_on if last_on is not None else samples[0][0]
    return max(0.0, now - start)


def _presence_false_streak_s(history: History, now: float) -> float | None:
    from .assistant import radar_person_present

    streak_start: float | None = None
    for ts, snapshot in history:
        if ts > now or "person_present" not in snapshot:
            continue
        if radar_person_present(snapshot):
            streak_start = None
        elif streak_start is None:
            streak_start = float(ts)
    return None if streak_start is None else max(0.0, now - streak_start)


def _multi_target_streak(history: History, now: float, thresholds: SnapshotThresholds) -> tuple[float | None, float | None, int | None, int]:
    streak_start: float | None = None
    last_ts: float | None = None
    last_count: int | None = None
    sample_count = 0
    for ts, snapshot in history:
        if ts > now or "target_count" not in snapshot:
            continue
        count_num = _finite_number(snapshot.get("target_count"))
        if count_num is not None and int(count_num) >= thresholds.caregiver_min_targets:
            if streak_start is None:
                streak_start = float(ts)
                sample_count = 0
            sample_count += 1
            last_ts = float(ts)
            last_count = int(count_num)
        else:
            streak_start = None
            last_ts = None
            last_count = None
            sample_count = 0
    return streak_start, last_ts, last_count, sample_count


def classify_presence(history: History, now: float, thresholds: SnapshotThresholds) -> PresenceInfo:
    raw, age = latest_value_age(history, "person_present", now)
    status = signal_status(age, thresholds.max_radar_age_s)
    target_count_raw, _ = latest_value_age(history, "target_count", now)
    distance_raw, _ = latest_value_age(history, "target_distance_cm", now)
    target_count_num = _finite_number(target_count_raw)
    distance = _finite_number(distance_raw)
    target_count = int(target_count_num) if target_count_num is not None else None

    if raw is None:
        return PresenceInfo(None, False, age, status, "missing", None, target_count, distance)

    radar_snapshot: dict[str, object] = {}
    for key in RADAR_KEYS:
        value, key_age = latest_value_age(history, key, now)
        if key_age is not None and key_age <= thresholds.max_radar_age_s:
            radar_snapshot[key] = value

    corroborated = False
    if raw is True and status == "fresh":
        from .assistant import radar_person_present

        corroborated = radar_person_present(radar_snapshot)
    if corroborated:
        return PresenceInfo(True, True, age, status, "corroborated", None, target_count, distance)
    false_streak_s = _presence_false_streak_s(history, now)
    if raw is True:
        return PresenceInfo(False, False, age, "uncorroborated", "uncorroborated", false_streak_s, target_count, distance)
    return PresenceInfo(False, False, age, status, "false", false_streak_s, target_count, distance)


def _motion_info(history: History, now: float, thresholds: SnapshotThresholds) -> MotionInfo:
    value_raw, age = latest_value_age(history, "motion_detected", now)
    value = bool(value_raw) if isinstance(value_raw, bool) else None
    transitions, last_ts = motion_transitions(history, now, thresholds.motion_window_s)
    quiet, _ = motion_transitions(history, now, thresholds.quiet_window_s)
    return MotionInfo(value, age, signal_status(age, thresholds.max_radar_age_s), transitions, quiet, last_ts, last_true_motion_ts(history, now), stillness_duration(history, now))


def _health(history: History, now: float, camera_frame_age_s: float | None, thresholds: SnapshotThresholds) -> dict[str, dict[str, object]]:
    readings_age = _last_sample_age(history, now)
    radar_age = _last_any_key_age(history, RADAR_KEYS, now)
    camera_status = signal_status(camera_frame_age_s, thresholds.max_camera_frame_age_s)
    return {
        "camera": {"status": camera_status, "age_s": _round(camera_frame_age_s), "source": "stream.frame_age"},
        "readings": {"status": signal_status(readings_age, thresholds.max_reading_age_s), "age_s": _round(readings_age), "source": "sensor_sampler"},
        "radar": {"status": signal_status(radar_age, thresholds.max_radar_age_s), "age_s": _round(radar_age), "source": "mr60_radar"},
        "history": {"status": signal_status(readings_age, thresholds.max_reading_age_s), "age_s": _round(readings_age), "source": "sampler_history"},
    }


def _health_bad(health: dict[str, dict[str, object]]) -> bool:
    return any(item["status"] in ("stale", "error") for item in health.values())


def _health_incomplete(health: dict[str, dict[str, object]]) -> bool:
    return any(item["status"] != "fresh" for item in health.values())


def _recent_motion_ts(motion: MotionInfo) -> float | None:
    candidates = [ts for ts in (motion.last_transition_ts, motion.last_true_ts) if ts is not None]
    return max(candidates) if candidates else None


def _label(state: str, *, now: float, no_presence_reading: bool, alert_age_s: float | None, motion: MotionInfo, crying_since_ts: float | None, caregiver: CaregiverInfo) -> str:
    if state == "crying":
        crying_for_s = 0.0 if crying_since_ts is None else max(0.0, now - crying_since_ts)
        return f"Crying detected — {int(max(alert_age_s or 0.0, crying_for_s) // 60)} min"
    if state == "sensor_unreliable":
        return "Sensors need attention"
    if state == "not_detected":
        return "No presence reading" if no_presence_reading else "No one detected"
    if state == "caregiver_present":
        count = caregiver.target_count or 0
        return f"Someone's in the room — {count} radar targets"
    if state == "wiggling":
        recent_motion_ts = _recent_motion_ts(motion)
        age = 0.0 if recent_motion_ts is None else max(0.0, now - recent_motion_ts)
        return f"Moving in the last {int(age // 60)} min"
    if state == "sleeping":
        return f"Still for {int((motion.still_for_s or 0.0) // 60)} min · best guess"
    if state == "calm":
        return "Quiet, occasional movement · best guess"
    return "Not sure right now — check the camera"


def _confidence(state: str, presence: PresenceInfo, motion: MotionInfo, health: dict[str, dict[str, object]], room_stale: bool, camera_age: float | None, cry_active: bool, cry_score: float | None) -> dict[str, str]:
    if state == "crying" and cry_active:
        score = "" if cry_score is None else f", cry score {cry_score:g}"
        return {"band": "high", "basis": f"active cry alert{score}"}
    if state == "caregiver_present":
        return {"band": "medium", "basis": "multiple radar targets; identity unknown"}
    if presence.value is None:
        return {"band": "low", "basis": "missing presence reading"}
    if state in ("sensor_unreliable", "uncertain") or _health_incomplete(health):
        return {"band": "low", "basis": "partial live-view signals"}
    if not presence.corroborated or presence.value is False or room_stale:
        return {"band": "medium", "basis": "direct current signal with one limited signal"}
    if motion.status == "fresh":
        if motion.still_for_s is not None:
            basis = f"fresh presence + no motion {int(motion.still_for_s // 60)} min"
        else:
            basis = "fresh presence + motion reading"
        if camera_age is not None:
            basis += f" + camera frame age {int(camera_age)}s"
        return {"band": "high", "basis": basis}
    return {"band": "medium", "basis": "fresh presence with limited motion detail"}


def _action(state: str, presence: PresenceInfo) -> dict[str, object]:
    if state in ("crying", "sensor_unreliable", "wiggling", "uncertain"):
        key, label = STATE_ACTIONS[state]
        detail = {
            "crying": "Cry alert is active.",
            "sensor_unreliable": "A required live-view signal is missing or stale.",
            "wiggling": "Movement was detected recently.",
            "uncertain": "The current readings do not agree enough.",
        }[state]
        signals = {
            "crying": ["cry_alert"],
            "sensor_unreliable": ["camera", "readings", "radar", "history"],
            "wiggling": ["motion", "camera"],
            "uncertain": ["presence", "motion", "camera"],
        }[state]
        return {"key": key, "label": label, "detail": detail, "evidence_signals": signals}
    if state == "caregiver_present":
        return {"key": "none", "label": "No suggested action", "detail": "Multiple radar targets are visible in the room.", "evidence_signals": ["presence", "motion"]}
    if state == "not_detected" and presence.value is None:
        return {"key": "check_room", "label": "Check the room", "detail": "There is no presence reading right now.", "evidence_signals": ["presence"]}
    if state == "not_detected":
        return {"key": "check_camera", "label": "Check the camera", "detail": "The presence reading does not show anyone.", "evidence_signals": ["presence", "camera"]}
    return {"key": "none", "label": "No suggested action", "detail": "Based on the current readings.", "evidence_signals": ["presence", "motion"]}


def _arousal(state: str, cry_score: float | None, transitions: int) -> float | None:
    if state in ("not_detected", "uncertain", "sensor_unreliable", "caregiver_present"):
        return None
    if state == "crying":
        return max(0.0, min(max(0.85, cry_score or 0.0), 1.0))
    if state == "wiggling":
        return min(0.5 + 0.1 * transitions, 0.8)
    if state == "calm":
        return 0.25
    if state == "sleeping":
        return 0.1
    return None


def _evidence_item(signal: str, label: str, value: object, unit: str | None, source: str, age_s: float | None, weight: float, status: str) -> dict[str, object]:
    return {"signal": signal, "label": label, "value": value, "unit": unit, "source": source, "age_s": _round(age_s), "weight": weight, "status": status}


def _evidence(state: str, presence: PresenceInfo, motion: MotionInfo, caregiver: CaregiverInfo, health: dict[str, dict[str, object]], room_temp: tuple[object | None, float | None], alerts: dict[str, object], thresholds: SnapshotThresholds) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    if state == "crying":
        items.append(_evidence_item("cry_alert", f"cry score {alerts.get('score', 0.0)}", alerts.get("score"), None, "alert_state", alerts.get("age_seconds") if isinstance(alerts.get("age_seconds"), (int, float)) else None, 1.0, "fresh" if alerts.get("active") else "stale"))
    if state == "sensor_unreliable":
        for signal, item in health.items():
            if item["status"] != "fresh":
                items.append(_evidence_item(signal, f"{signal} signal", item.get("age_s"), "s", str(item["source"]), item.get("age_s") if isinstance(item.get("age_s"), (int, float)) else None, 1.0, str(item["status"])))
    if presence.note == "uncorroborated":
        items.append(_evidence_item("presence", "radar flag not corroborated", False, None, "mr60_radar", presence.age_s, 0.9, "uncorroborated"))
    elif presence.value is None:
        items.append(_evidence_item("presence", "No presence reading", None, None, "mr60_radar", presence.age_s, 1.0, "missing"))
    else:
        label = "Presence corroborated" if presence.corroborated else "Presence reading"
        items.append(_evidence_item("presence", label, presence.value, None, "mr60_radar", presence.age_s, 0.8, presence.status if presence.status != "uncorroborated" else "uncorroborated"))
    if state == "caregiver_present":
        items.append(_evidence_item("target_count", "Radar target count", caregiver.target_count, None, "mr60_radar", caregiver.age_s, 0.9, signal_status(caregiver.age_s, thresholds.max_radar_age_s)))
    if motion.value is not None or state in ("wiggling", "sleeping", "calm"):
        label = "Motion transition" if state == "wiggling" else ("Still duration" if state == "sleeping" else "Motion reading")
        value = motion.transitions_window if state == "wiggling" else motion.value
        items.append(_evidence_item("motion", label, value, None, "mr60_radar", motion.age_s, 0.7, motion.status))
    camera = health["camera"]
    items.append(_evidence_item("camera", "Camera frame age", camera["age_s"], "s", "stream.frame_age", camera["age_s"] if isinstance(camera["age_s"], (int, float)) else None, 0.6, str(camera["status"])))
    temp_value, temp_age = room_temp
    if temp_value is not None:
        items.append(_evidence_item("room_temperature_c", "Room temperature", temp_value, "°C", "bme688", temp_age, 0.4, signal_status(temp_age, thresholds.max_reading_age_s)))
    return items[: max(1, thresholds.max_evidence_items)]


class LiveSnapshotEngine:
    def __init__(self, thresholds: SnapshotThresholds | None = None, process_start_ts: float | None = None) -> None:
        self.thresholds = thresholds or SnapshotThresholds()
        self._process_start_ts = process_start_ts
        self._restart_notice_enabled = process_start_ts is not None
        self._state: str | None = None
        self._since_ts: float | None = None
        self._sensor_unreliable = False
        self._bad_health_checks = 0
        self._good_health_checks = 0
        self._last_cry_active_ts: float | None = None
        self._last_alert_age_s: float | None = None
        self._room_temp_side: str | None = None
        self._caregiver_latched = False
        self._caregiver_last_multi_ts: float | None = None
        self._caregiver_last_target_count: int | None = None
        self._t2_seq = 0
        self._t2_active: dict[str, _T2AlertState] = {}
        self._t2_cleared_ts: dict[str, float] = {}
        self._device_restart_seen = False

    def build(self, *, history: History, now: float, alerts: dict[str, object], mode: str, mode_auto: bool, camera_frame_age_s: float | None, soothe_playing: str | None, autosoothe: dict[str, object] | None) -> dict[str, object]:
        if self._process_start_ts is None:
            self._process_start_ts = now
        thresholds = self.thresholds
        presence = classify_presence(history, now, thresholds)
        motion = _motion_info(history, now, thresholds)
        health = _health(history, now, camera_frame_age_s, thresholds)
        self._update_health_state(_health_bad(health))
        caregiver = self._caregiver_info(history, now, presence)

        alert_age = alerts.get("age_seconds") if isinstance(alerts.get("age_seconds"), (int, float)) else None
        cry_score = _finite_number(alerts.get("score"))
        if alerts.get("active") is True:
            self._last_cry_active_ts = now
            self._last_alert_age_s = alert_age
        cry_active = alerts.get("active") is True or (
            self._last_cry_active_ts is not None
            and now - self._last_cry_active_ts <= thresholds.cry_clear_grace_s
        )
        if alerts.get("active") is not True:
            alert_age = self._last_alert_age_s

        state = self._choose_state(now, cry_active, presence, motion, caregiver)
        no_presence_reading = presence.value is None
        state = self._apply_dwell(state, now)
        if state != self._state:
            self._state = state
            self._since_ts = now

        room = self._room(history, now)
        room_temp = latest_value_age(history, "room_temperature_c", now)
        room_action = self._room_action(room_temp)
        room_stale = any(
            latest_value_age(history, key, now)[1] is not None
            and latest_value_age(history, key, now)[1] > thresholds.max_reading_age_s
            for key, _unit in ROOM_KEYS.values()
        )
        confidence = _confidence(state, presence, motion, health, room_stale, camera_frame_age_s, alerts.get("active") is True, cry_score)
        evidence = _evidence(state, presence, motion, caregiver, health, room_temp, alerts, thresholds)
        active_alerts = self._alerts(alerts, now, health, room_temp, room_action)
        autosoothe = autosoothe or {}

        return {
            "schema_version": 1,
            "generated_ts": now,
            "baby_state": state,
            "label": _label(state, now=now, no_presence_reading=no_presence_reading, alert_age_s=alert_age, motion=motion, crying_since_ts=self._since_ts if state == "crying" else None, caregiver=caregiver),
            "arousal_score": _arousal(state, cry_score, motion.transitions_window),
            "confidence": confidence,
            "since_ts": self._since_ts,
            "recommended_action": _action(state, presence),
            "room_action": room_action,
            "evidence": evidence,
            "room": room,
            "audio": {"cry_alert_active": alerts.get("active") is True, "cry_score": cry_score if alerts.get("active") is True else None, "soothe_playing": soothe_playing, "autosoothe_enabled": bool(autosoothe.get("enabled", False)), "autosoothe_preset": str(autosoothe.get("preset", ""))},
            "vision": {"mode": mode, "mode_auto": bool(mode_auto), "camera_frame_age_s": _round(camera_frame_age_s)},
            "presence": {"value": presence.value, "corroborated": presence.corroborated, "age_s": _round(presence.age_s), "target_count": presence.target_count, "target_distance_cm": presence.target_distance_cm},
            "motion": {"value": motion.value, "age_s": _round(motion.age_s), "transitions_window": motion.transitions_window, "still_for_s": _round(motion.still_for_s)},
            "vitals": self._vitals(history, now),
            "alerts": active_alerts,
            "device": {"uptime_s": _round(now - self._process_start_ts), "server_time_ts": now},
            "health": health,
        }

    def _update_health_state(self, bad: bool) -> None:
        t = self.thresholds
        if self._sensor_unreliable:
            self._good_health_checks = self._good_health_checks + 1 if not bad else 0
            if self._good_health_checks >= t.health_recovered_checks_to_exit:
                self._sensor_unreliable = False
                self._bad_health_checks = 0
        else:
            self._bad_health_checks = self._bad_health_checks + 1 if bad else 0
            self._good_health_checks = 0 if bad else self._good_health_checks
            if self._bad_health_checks >= t.health_bad_checks_to_enter:
                self._sensor_unreliable = True

    def _caregiver_info(self, history: History, now: float, presence: PresenceInfo) -> CaregiverInfo:
        t = self.thresholds
        streak_start, last_ts, target_count, sample_count = _multi_target_streak(history, now, t)
        age_s = None if last_ts is None else max(0.0, now - last_ts)
        sustained_s = None if streak_start is None else max(0.0, now - streak_start)
        current_multi = (
            presence.value is True
            and presence.corroborated
            and last_ts is not None
            and age_s is not None
            and age_s <= t.max_radar_age_s
            and sample_count >= 2
        )
        if current_multi:
            self._caregiver_last_multi_ts = last_ts
            self._caregiver_last_target_count = target_count
        if current_multi and (sustained_s or 0.0) >= t.caregiver_dwell_s:
            self._caregiver_latched = True
            return CaregiverInfo(True, target_count, age_s, sustained_s, False)
        if (
            self._caregiver_latched
            and presence.value is True
            and presence.corroborated
            and self._caregiver_last_multi_ts is not None
            and now - self._caregiver_last_multi_ts <= t.caregiver_release_s
        ):
            held_age = max(0.0, now - self._caregiver_last_multi_ts)
            return CaregiverInfo(True, self._caregiver_last_target_count, held_age, None, True)
        self._caregiver_latched = False
        return CaregiverInfo(False, target_count, age_s, sustained_s, False)

    def _choose_state(self, now: float, cry_active: bool, presence: PresenceInfo, motion: MotionInfo, caregiver: CaregiverInfo) -> str:
        t = self.thresholds
        if cry_active:
            return "crying"
        if self._sensor_unreliable:
            return "sensor_unreliable"
        if presence.value is None:
            return "not_detected"
        if presence.value is False:
            if (presence.false_streak_s or 0.0) >= t.presence_false_dwell_s:
                return "not_detected"
            return self._state if self._state and self._state != "caregiver_present" else "uncertain"
        if caregiver.active:
            return "caregiver_present"
        recent_motion_ts = _recent_motion_ts(motion)
        if recent_motion_ts is not None and now - recent_motion_ts <= t.wiggling_release_s:
            return "wiggling"
        if motion.still_for_s is not None and motion.still_for_s >= t.still_min_s:
            return "sleeping"
        if motion.value is False and motion.quiet_transitions <= t.quiet_max_motion_transitions:
            return "calm"
        return "uncertain"

    def _apply_dwell(self, candidate: str, now: float) -> str:
        quiet_states = {"sleeping", "calm", "uncertain"}
        if self._state in quiet_states and candidate in quiet_states and candidate != self._state:
            if self._since_ts is not None and now - self._since_ts < self.thresholds.state_min_dwell_s:
                return self._state
        return candidate

    def _room(self, history: History, now: float) -> dict[str, dict[str, object]]:
        room: dict[str, dict[str, object]] = {}
        for out_key, (raw_key, _unit) in ROOM_KEYS.items():
            value, age = latest_value_age(history, raw_key, now)
            number = _finite_number(value)
            if out_key == "gas_kohm" and number is not None:
                number = number / 1000.0
            room[out_key] = {"value": None if number is None else round(number, 3), "age_s": _round(age)}
        return room

    def _room_action(self, temp: tuple[object | None, float | None]) -> dict[str, object] | None:
        value = _finite_number(temp[0])
        if value is None:
            return None
        t = self.thresholds
        if value < t.room_cold_below_c:
            self._room_temp_side = "cold"
        elif value > t.room_warm_above_c:
            self._room_temp_side = "warm"
        elif self._room_temp_side == "cold" and value >= t.room_cold_below_c + t.room_temp_hysteresis_c:
            self._room_temp_side = None
        elif self._room_temp_side == "warm" and value <= t.room_warm_above_c - t.room_temp_hysteresis_c:
            self._room_temp_side = None
        if self._room_temp_side is None:
            return None
        side = "below" if self._room_temp_side == "cold" else "above"
        bound = t.room_cold_below_c if self._room_temp_side == "cold" else t.room_warm_above_c
        return {"key": "adjust_room", "label": "Adjust room", "detail": f"Room temperature is {side} {bound:g} °C.", "evidence_signals": ["room_temperature_c"]}

    def _vitals(self, history: History, now: float) -> dict[str, object]:
        resp, resp_age = latest_value_age(history, "radar_respiratory_rate", now)
        resp_num = _finite_number(resp)
        heart_num: float | None = None
        if resp_num is not None:
            heart, _heart_age = latest_value_age(history, "radar_heart_rate_bpm", now)
            heart_num = _finite_number(heart)
        return {"respiratory_rate": resp_num, "heart_rate_bpm": heart_num, "age_s": _round(resp_age) if resp_num is not None else None, "caveat": "rough radar estimate"}

    def _t2_conditions(self, now: float, health: dict[str, dict[str, object]], room_temp: tuple[object | None, float | None], room_action: dict[str, object] | None) -> dict[str, dict[str, object]]:
        t = self.thresholds
        conditions: dict[str, dict[str, object]] = {}
        temp = _finite_number(room_temp[0])
        if room_action is not None and temp is not None and self._room_temp_side in {"warm", "cold"}:
            side = self._room_temp_side
            alert_type = "room_warm" if side == "warm" else "room_cool"
            title = "Room a bit warm" if side == "warm" else "Room a bit cool"
            conditions[alert_type] = {
                "title": title,
                "message": f"Temperature {temp:g}°C; usual room range {t.room_cold_below_c:g}-{t.room_warm_above_c:g}°C.",
                "confidence": {"band": "medium", "basis": "direct room temperature reading"},
                "evidence": [_evidence_item("room_temperature_c", "Room temperature", temp, "°C", "bme688", room_temp[1], 1.0, signal_status(room_temp[1], t.max_reading_age_s))],
                "action": {"key": "adjust_room", "label": "Adjust room", "detail": str(room_action.get("detail", "Room temperature needs attention.")), "evidence_signals": ["room_temperature_c"]},
            }

        stale_signals = [
            (signal, item)
            for signal, item in health.items()
            if signal != "camera" and item["status"] in ("stale", "error")
        ]
        if self._sensor_unreliable and stale_signals:
            ages = [
                float(item["age_s"])
                for _signal, item in stale_signals
                if isinstance(item.get("age_s"), (int, float))
            ]
            age = max(ages) if ages else None
            names = ", ".join(signal for signal, _item in stale_signals)
            age_text = f"{int(age or 0)}s" if age is not None else "unknown age"
            conditions["sensor_stale"] = {
                "title": "Sensor readings stale",
                "message": f"No fresh {names} reading for {age_text}.",
                "confidence": {"band": "low", "basis": "latched stale live-view signal"},
                "evidence": [
                    _evidence_item(signal, f"{signal} signal", item.get("age_s"), "s", str(item["source"]), item.get("age_s") if isinstance(item.get("age_s"), (int, float)) else None, 1.0, str(item["status"]))
                    for signal, item in stale_signals
                ],
                "action": {"key": "reposition_device", "label": "Check the device", "detail": "A required live-view signal is stale.", "evidence_signals": [signal for signal, _item in stale_signals]},
            }

        camera = health["camera"]
        if self._sensor_unreliable and camera["status"] in ("stale", "error"):
            age = camera.get("age_s") if isinstance(camera.get("age_s"), (int, float)) else None
            conditions["camera_down"] = {
                "title": "Camera not reachable",
                "message": f"No camera frame for {int(age or 0)}s.",
                "confidence": {"band": "low", "basis": "latched camera health signal"},
                "evidence": [_evidence_item("camera", "Camera frame age", camera.get("age_s"), "s", str(camera["source"]), age, 1.0, str(camera["status"]))],
                "action": {"key": "check_camera", "label": "Check the camera", "detail": "The camera frame is stale.", "evidence_signals": ["camera"]},
            }

        uptime_s = max(0.0, now - (self._process_start_ts or now))
        if self._restart_notice_enabled and not self._device_restart_seen and uptime_s < t.device_restart_notice_s:
            conditions["device_restarted"] = {
                "title": "Device restarted",
                "message": "Readings resumed after a restart.",
                "confidence": {"band": "medium", "basis": "process uptime below restart notice threshold"},
                "evidence": [_evidence_item("device", "Process uptime", _round(uptime_s), "s", "process", uptime_s, 0.7, "fresh")],
                "action": {"key": "none", "label": "No suggested action", "detail": "Review recent readings.", "evidence_signals": ["device"]},
            }
        return conditions

    def _t2_item(self, alert_type: str, payload: dict[str, object], state: _T2AlertState, now: float) -> dict[str, object]:
        return {
            "tier": "T2",
            "type": alert_type,
            "title": str(payload["title"]),
            "message": str(payload["message"]),
            "state": "active",
            "seq": state.seq,
            "raised_ts": state.raised_ts,
            "age_s": _round(now - state.raised_ts),
            "active": True,
            "confidence": payload["confidence"],
            "evidence": payload["evidence"],
            "action": payload["action"],
            "notification": {"browser": True, "sound": False},
        }

    def _t2_alerts(self, now: float, health: dict[str, dict[str, object]], room_temp: tuple[object | None, float | None], room_action: dict[str, object] | None) -> list[dict[str, object]]:
        conditions = self._t2_conditions(now, health, room_temp, room_action)
        for alert_type in list(self._t2_active):
            if alert_type not in conditions:
                self._t2_active.pop(alert_type, None)
                self._t2_cleared_ts[alert_type] = now
                if alert_type == "device_restarted":
                    self._device_restart_seen = True

        items: list[dict[str, object]] = []
        for alert_type in ("room_warm", "room_cool", "sensor_stale", "camera_down", "device_restarted"):
            payload = conditions.get(alert_type)
            if payload is None:
                continue
            state = self._t2_active.get(alert_type)
            if state is None:
                if alert_type == "device_restarted":
                    if self._device_restart_seen:
                        continue
                else:
                    cleared_ts = self._t2_cleared_ts.get(alert_type)
                    if cleared_ts is not None and now - cleared_ts < self.thresholds.t2_repeat_cooldown_s:
                        continue
                self._t2_seq += 1
                state = _T2AlertState(self._t2_seq, now)
                self._t2_active[alert_type] = state
            items.append(self._t2_item(alert_type, payload, state, now))
        return items

    def _alerts(self, alerts: dict[str, object], now: float, health: dict[str, dict[str, object]], room_temp: tuple[object | None, float | None], room_action: dict[str, object] | None) -> list[dict[str, object]]:
        active_alerts: list[dict[str, object]] = []
        if alerts.get("active") is not True:
            return self._t2_alerts(now, health, room_temp, room_action)
        age = alerts.get("age_seconds")
        active_alerts.append({"tier": "T1", "type": "cry_sustained", "title": str(alerts.get("title", "")), "message": str(alerts.get("message", "")), "score": _finite_number(alerts.get("score")) or 0.0, "seq": int(alerts.get("seq", 0) or 0), "age_s": _round(age if isinstance(age, (int, float)) else None), "active": True})
        active_alerts.extend(self._t2_alerts(now, health, room_temp, room_action))
        return active_alerts
