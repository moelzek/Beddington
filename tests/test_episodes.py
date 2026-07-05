"""EpisodeTracker: derived parent-friendly episodes from sensor ticks."""

from beddington.episodes import EpisodeChange, EpisodeThresholds, EpisodeTracker


def _changes(tracker, ts, snapshot, camera_age=None):
    return tracker.update(ts, snapshot, camera_age)


def test_stirring_opens_on_motion_and_closes_after_gap() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(stir_gap_s=120))
    assert _changes(tracker, 0.0, {"motion_detected": False}) == []
    started = _changes(tracker, 10.0, {"motion_detected": True})
    assert started == [EpisodeChange("start", "stirring", 10.0)]
    # More motion keeps the same episode open (no duplicate start).
    assert _changes(tracker, 40.0, {"motion_detected": True}) == []
    # Quiet, but not yet past the gap.
    assert _changes(tracker, 100.0, {"motion_detected": False}) == []
    ended = _changes(tracker, 161.0, {"motion_detected": False})
    # Ends at the LAST movement actually seen, not at the gap boundary.
    assert ended == [EpisodeChange("end", "stirring", 40.0)]


def test_crying_opens_and_missing_state_does_not_close() -> None:
    tracker = EpisodeTracker()
    assert _changes(tracker, 0.0, {"cry_alert_active": False}) == []
    assert _changes(tracker, 10.0, {"cry_alert_active": True}) == [
        EpisodeChange("start", "crying", 10.0)
    ]
    assert _changes(tracker, 20.0, {}) == []
    assert _changes(tracker, 30.0, {"cry_alert_active": None}) == []
    assert _changes(tracker, 40.0, {"cry_alert_active": False}) == [
        EpisodeChange("end", "crying", 40.0)
    ]


def test_presence_needs_dwell_both_ways() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(presence_open_s=10, presence_close_s=30))
    assert _changes(tracker, 0.0, {"person_present": True}) == []
    started = _changes(tracker, 12.0, {"person_present": True})
    assert started == [EpisodeChange("start", "caregiver_present", 0.0)]
    # A single false tick does not close it.
    assert _changes(tracker, 20.0, {"person_present": False}) == []
    assert _changes(tracker, 25.0, {"person_present": True}) == []
    assert _changes(tracker, 40.0, {"person_present": False}) == []
    ended = _changes(tracker, 71.0, {"person_present": False})
    assert ended == [EpisodeChange("end", "caregiver_present", 40.0)]


def test_presence_missing_reading_holds_state() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(presence_open_s=0, presence_close_s=30))
    assert _changes(tracker, 0.0, {"person_present": True}) == [
        EpisodeChange("start", "caregiver_present", 0.0)
    ]
    # Sensor silence must not end the visit.
    assert _changes(tracker, 500.0, {}) == []


def test_room_warm_dwell_and_hysteresis() -> None:
    tracker = EpisodeTracker(
        EpisodeThresholds(warm_c=24.0, temp_hysteresis_c=0.5, temp_dwell_s=300)
    )
    assert _changes(tracker, 0.0, {"room_temperature_c": 24.5}) == []
    assert _changes(tracker, 200.0, {"room_temperature_c": 24.6}) == []
    started = _changes(tracker, 301.0, {"room_temperature_c": 24.4})
    assert started == [EpisodeChange("start", "room_warm", 0.0)]
    # Dropping below the threshold but inside the hysteresis band keeps it open.
    assert _changes(tracker, 400.0, {"room_temperature_c": 23.8}) == []
    ended = _changes(tracker, 500.0, {"room_temperature_c": 23.2})
    assert ended == [EpisodeChange("end", "room_warm", 500.0)]


def test_room_warm_flap_resets_dwell() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(temp_dwell_s=300))
    assert _changes(tracker, 0.0, {"room_temperature_c": 24.5}) == []
    # A cool dip resets the dwell clock — no episode from a brief spike.
    assert _changes(tracker, 100.0, {"room_temperature_c": 22.0}) == []
    assert _changes(tracker, 350.0, {"room_temperature_c": 24.5}) == []


def test_room_cold_episode() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(cold_c=16.0, temp_dwell_s=60))
    assert _changes(tracker, 0.0, {"room_temperature_c": 15.5}) == []
    started = _changes(tracker, 61.0, {"room_temperature_c": 15.0})
    assert started == [EpisodeChange("start", "room_cold", 0.0)]
    ended = _changes(tracker, 120.0, {"room_temperature_c": 17.0})
    assert ended == [EpisodeChange("end", "room_cold", 120.0)]


def test_sensor_unavailable_after_sustained_absence() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(sensor_missing_s=60))
    assert _changes(tracker, 0.0, {"room_temperature_c": 20.0}) == []
    assert _changes(tracker, 30.0, {}) == []
    started = _changes(tracker, 91.0, {})
    assert started == [
        EpisodeChange("start", "sensor_unavailable", 30.0, "room_temperature_c")
    ]
    ended = _changes(tracker, 150.0, {"room_temperature_c": 20.5})
    assert ended == [
        EpisodeChange("end", "sensor_unavailable", 150.0, "room_temperature_c")
    ]


def test_total_outage_flags_every_seen_sensor() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(sensor_missing_s=60))
    _changes(tracker, 0.0, {"room_temperature_c": 20.0, "motion_detected": False})
    assert _changes(tracker, 30.0, {}) == []  # missing-clock starts here
    changes = _changes(tracker, 100.0, {})
    kinds = {(c.kind, c.detail) for c in changes}
    assert kinds == {
        ("sensor_unavailable", "room_temperature_c"),
        ("sensor_unavailable", "motion_detected"),
    }


def test_camera_stale_opens_baby_not_visible() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(camera_stale_s=30))
    # No camera info at all: unknown, never an episode.
    assert _changes(tracker, 0.0, {}, camera_age=None) == []
    assert _changes(tracker, 10.0, {}, camera_age=2.0) == []
    started = _changes(tracker, 60.0, {}, camera_age=45.0)
    # Starts when the frames actually stopped (now - age).
    assert started == [EpisodeChange("start", "baby_not_visible", 15.0)]
    ended = _changes(tracker, 70.0, {}, camera_age=1.0)
    assert ended == [EpisodeChange("end", "baby_not_visible", 69.0)]


def test_flush_closes_everything_open() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(presence_open_s=0))
    tracker.update(0.0, {"motion_detected": True, "person_present": True})
    changes = tracker.flush(50.0)
    assert {(c.action, c.kind) for c in changes} == {
        ("end", "caregiver_present"),
        ("end", "stirring"),
    }
    assert all(c.ts == 50.0 for c in changes)
    assert tracker.open_episodes() == {}


def test_end_never_precedes_start() -> None:
    tracker = EpisodeTracker(EpisodeThresholds(camera_stale_s=30))
    tracker.update(100.0, {}, 60.0)  # opens at 40.0
    # Age jumps larger than elapsed time (clock weirdness): end clamps to start.
    ended = tracker.update(101.0, {}, 200.0)
    assert ended == []  # still stale, still open
    closed = tracker.update(102.0, {}, 0.0)
    assert closed[0].ts >= 40.0
