from __future__ import annotations

import re

from beddington.live_snapshot import LiveSnapshotEngine

NOW = 1_000.0
ACTION_KEYS = {
    "none",
    "check_room",
    "comfort_now",
    "reposition_device",
    "check_power",
    "adjust_room",
    "check_camera",
}
TOP_KEYS = {
    "schema_version",
    "generated_ts",
    "baby_state",
    "label",
    "arousal_score",
    "confidence",
    "since_ts",
    "recommended_action",
    "room_action",
    "evidence",
    "room",
    "audio",
    "vision",
    "presence",
    "motion",
    "vitals",
    "alerts",
    "device",
    "health",
}


def _alerts(active: bool = False, score: float = 0.9, age: float | None = 5.0) -> dict[str, object]:
    return {
        "active": active,
        "title": "Cry detected",
        "message": "cry score 0.9",
        "score": score,
        "seq": 7,
        "age_seconds": age,
    }


def _sample(*, present: object = True, target: bool = True, motion: object = False, temp: float = 19.0) -> dict[str, object]:
    sample: dict[str, object] = {
        "room_temperature_c": temp,
        "room_humidity_pct": 51.0,
        "room_pressure_hpa": 1013.0,
        "room_gas_resistance_ohms": 112_000.0,
        "room_illuminance_lx": 4.0,
    }
    if present is not None:
        sample["person_present"] = present
    if target:
        sample["target_count"] = 1
        sample["target_distance_cm"] = 75.0
    if motion is not None:
        sample["motion_detected"] = motion
    return sample


def _room_only(temp: float = 19.0) -> dict[str, object]:
    return {
        "room_temperature_c": temp,
        "room_humidity_pct": 51.0,
        "room_pressure_hpa": 1013.0,
        "room_gas_resistance_ohms": 112_000.0,
        "room_illuminance_lx": 4.0,
    }


def _sleep_history(now: float = NOW) -> list[tuple[float, dict[str, object]]]:
    return [
        (now - 1_260.0, _sample(motion=False)),
        (now - 2.0, _sample(motion=False)),
    ]


def _build(
    engine: LiveSnapshotEngine,
    history: list[tuple[float, dict[str, object]]],
    *,
    now: float = NOW,
    alerts: dict[str, object] | None = None,
    camera_age: float | None = 1.0,
) -> dict[str, object]:
    return engine.build(
        history=history,
        now=now,
        alerts=alerts or _alerts(False),
        mode="night",
        mode_auto=True,
        camera_frame_age_s=camera_age,
        soothe_playing=None,
        autosoothe={"enabled": False, "preset": ""},
    )


def test_active_cry_alert_beats_stillness_and_emits_alert_item() -> None:
    snapshot = _build(LiveSnapshotEngine(), _sleep_history(), alerts=_alerts(True, score=0.92, age=65.0))

    assert snapshot["baby_state"] == "crying"
    assert snapshot["label"] == "Crying detected — 1 min"
    assert snapshot["recommended_action"]["key"] == "comfort_now"
    assert snapshot["arousal_score"] == 0.92
    assert snapshot["alerts"] == [
        {
            "tier": "T1",
            "type": "cry_sustained",
            "title": "Cry detected",
            "message": "cry score 0.9",
            "score": 0.92,
            "seq": 7,
            "age_s": 65.0,
            "active": True,
        }
    ]


def test_camera_down_enters_sensor_unreliable_after_two_bad_builds() -> None:
    engine = LiveSnapshotEngine()

    first = _build(engine, _sleep_history(NOW), camera_age=9.0)
    second = _build(engine, _sleep_history(NOW + 1.0), now=NOW + 1.0, camera_age=9.0)

    assert first["baby_state"] == "sleeping"
    assert second["baby_state"] == "sensor_unreliable"
    assert second["label"] == "Sensors need attention"


def test_missing_health_never_triggers_sensor_unreliable() -> None:
    radar_disabled = LiveSnapshotEngine()
    for offset in range(4):
        snapshot = _build(
            radar_disabled,
            [(NOW + offset - 2.0, _room_only())],
            now=NOW + offset,
        )
        assert snapshot["health"]["radar"]["status"] == "missing"
        assert snapshot["baby_state"] != "sensor_unreliable"

    no_camera_yet = LiveSnapshotEngine()
    for offset in range(4):
        snapshot = _build(
            no_camera_yet,
            _sleep_history(NOW + offset),
            now=NOW + offset,
            camera_age=None,
        )
        assert snapshot["health"]["camera"]["status"] == "missing"
        assert snapshot["baby_state"] != "sensor_unreliable"


def test_stale_seen_radar_triggers_sensor_unreliable_after_two_bad_builds() -> None:
    engine = LiveSnapshotEngine()

    def history(now: float) -> list[tuple[float, dict[str, object]]]:
        return [
            (now - 20.0, _sample(motion=False)),
            (now - 2.0, _room_only()),
        ]

    first = _build(engine, history(NOW), now=NOW)
    second = _build(engine, history(NOW + 1.0), now=NOW + 1.0)

    assert first["health"]["radar"]["status"] == "stale"
    assert first["baby_state"] != "sensor_unreliable"
    assert second["baby_state"] == "sensor_unreliable"


def test_presence_missing_vs_false_have_distinct_not_detected_labels() -> None:
    missing = _build(LiveSnapshotEngine(), [(NOW - 2.0, _sample(present=None, motion=False))])
    false = _build(
        LiveSnapshotEngine(),
        [
            (NOW - 12.0, _sample(present=False, target=False, motion=False)),
            (NOW - 2.0, _sample(present=False, target=False, motion=False)),
        ],
    )

    assert missing["baby_state"] == "not_detected"
    assert missing["label"] == "No presence reading"
    assert false["baby_state"] == "not_detected"
    assert false["label"] == "No one detected"


def test_crying_persists_for_clear_grace_then_releases() -> None:
    engine = LiveSnapshotEngine()

    assert _build(engine, _sleep_history(NOW), alerts=_alerts(True), now=NOW)["baby_state"] == "crying"
    grace = _build(engine, _sleep_history(NOW + 29.0), now=NOW + 29.0, alerts=_alerts(False, age=None))
    released = _build(engine, _sleep_history(NOW + 31.0), now=NOW + 31.0, alerts=_alerts(False, age=None))

    assert grace["baby_state"] == "crying"
    assert released["baby_state"] == "sleeping"


def test_crying_label_uses_state_duration_across_realert() -> None:
    engine = LiveSnapshotEngine()

    first = _build(engine, _sleep_history(NOW), now=NOW, alerts=_alerts(True, age=5.0))
    relert = _build(
        engine,
        _sleep_history(NOW + 130.0),
        now=NOW + 130.0,
        alerts=_alerts(True, age=5.0),
    )

    assert first["label"] == "Crying detected — 0 min"
    assert relert["label"] == "Crying detected — 2 min"


def test_crying_confidence_uses_active_alert_direct_signal() -> None:
    snapshot = _build(
        LiveSnapshotEngine(),
        [(NOW - 2.0, _room_only())],
        alerts=_alerts(True, score=0.91, age=3.0),
    )

    assert snapshot["baby_state"] == "crying"
    assert snapshot["confidence"] == {
        "band": "high",
        "basis": "active cry alert, cry score 0.91",
    }


def test_sensor_unreliable_needs_two_bad_and_three_recovered_builds() -> None:
    engine = LiveSnapshotEngine()
    assert _build(engine, _sleep_history(NOW), camera_age=9.0)["baby_state"] == "sleeping"
    assert _build(engine, _sleep_history(NOW + 1), now=NOW + 1, camera_age=9.0)["baby_state"] == "sensor_unreliable"
    assert _build(engine, _sleep_history(NOW + 2), now=NOW + 2)["baby_state"] == "sensor_unreliable"
    assert _build(engine, _sleep_history(NOW + 3), now=NOW + 3)["baby_state"] == "sensor_unreliable"
    assert _build(engine, _sleep_history(NOW + 4), now=NOW + 4)["baby_state"] == "sleeping"


def test_wiggling_sleeping_calm_uncertain_and_dwell() -> None:
    wiggling_history = [
        (NOW - 80.0, _sample(motion=False)),
        (NOW - 70.0, _sample(motion=True)),
        (NOW - 2.0, _sample(motion=False)),
    ]
    assert _build(LiveSnapshotEngine(), wiggling_history)["baby_state"] == "wiggling"

    continuous_motion = [
        (NOW - 180.0, _sample(motion=True)),
        (NOW - 90.0, _sample(motion=True)),
        (NOW - 2.0, _sample(motion=True)),
    ]
    moving = _build(LiveSnapshotEngine(), continuous_motion)
    assert moving["baby_state"] == "wiggling"
    assert moving["baby_state"] != "calm"

    assert _build(LiveSnapshotEngine(), _sleep_history())["baby_state"] == "sleeping"

    calm_history = [
        (NOW - 220.0, _sample(motion=False)),
        (NOW - 200.0, _sample(motion=True)),
        (NOW - 2.0, _sample(motion=False)),
    ]
    assert _build(LiveSnapshotEngine(), calm_history)["baby_state"] == "calm"

    uncertain_history = [(NOW - 2.0, _sample(motion=None))]
    assert _build(LiveSnapshotEngine(), uncertain_history)["baby_state"] == "uncertain"

    engine = LiveSnapshotEngine()
    assert _build(engine, calm_history, now=NOW)["baby_state"] == "calm"
    assert _build(engine, _sleep_history(NOW + 10), now=NOW + 10)["baby_state"] == "calm"
    assert _build(engine, _sleep_history(NOW + 21), now=NOW + 21)["baby_state"] == "sleeping"


def test_presence_false_dwell_holds_prior_state_then_not_detected() -> None:
    engine = LiveSnapshotEngine()
    assert _build(engine, _sleep_history(NOW), now=NOW)["baby_state"] == "sleeping"

    blip_now = NOW + 2.0
    false_blip = [
        (blip_now - 1_260.0, _sample(motion=False)),
        (blip_now - 20.0, _sample(motion=False)),
        (blip_now - 2.0, _sample(present=False, target=False, motion=False)),
    ]
    blip = _build(engine, false_blip, now=blip_now)

    assert blip["baby_state"] == "sleeping"

    sustained = _build(
        LiveSnapshotEngine(),
        [
            (NOW - 12.0, _sample(present=False, target=False, motion=False)),
            (NOW - 2.0, _sample(present=False, target=False, motion=False)),
        ],
    )
    assert sustained["baby_state"] == "not_detected"
    assert sustained["label"] == "No one detected"


def test_uncorroborated_presence_flag_is_not_presence_and_is_evidence() -> None:
    snapshot = _build(
        LiveSnapshotEngine(),
        [
            (NOW - 12.0, _sample(target=False, motion=False)),
            (NOW - 2.0, _sample(target=False, motion=False)),
        ],
    )

    assert snapshot["baby_state"] == "not_detected"
    assert snapshot["presence"]["value"] is False
    assert any(item["label"] == "radar flag not corroborated" for item in snapshot["evidence"])


def test_confidence_high_medium_low_bands() -> None:
    high = _build(LiveSnapshotEngine(), _sleep_history())
    medium_history = [
        (NOW - 30.0, {"room_temperature_c": 19.0}),
        (NOW - 2.0, _sample(motion=False) | {"room_temperature_c": 19.0}),
    ]
    medium_history[1][1].pop("room_temperature_c")
    medium = _build(LiveSnapshotEngine(), medium_history)
    low = _build(LiveSnapshotEngine(), [(NOW - 2.0, _sample(present=None, motion=False))])

    assert high["confidence"]["band"] == "high"
    assert medium["confidence"]["band"] == "medium"
    assert low["confidence"]["band"] == "low"


def test_room_action_temperature_hysteresis_warm_and_cold() -> None:
    warm = LiveSnapshotEngine()
    assert _build(warm, [(NOW - 2.0, _sample(temp=20.2))])["room_action"]["key"] == "adjust_room"
    assert _build(warm, [(NOW - 2.0, _sample(temp=19.7))])["room_action"]["key"] == "adjust_room"
    assert _build(warm, [(NOW - 2.0, _sample(temp=19.4))])["room_action"] is None

    cold = LiveSnapshotEngine()
    assert _build(cold, [(NOW - 2.0, _sample(temp=15.8))])["room_action"]["key"] == "adjust_room"
    assert _build(cold, [(NOW - 2.0, _sample(temp=16.3))])["room_action"]["key"] == "adjust_room"
    assert _build(cold, [(NOW - 2.0, _sample(temp=16.6))])["room_action"] is None


def test_vitals_suppress_heart_without_respiratory_and_use_exact_caveat() -> None:
    heart_only = [(NOW - 2.0, _sample(motion=False) | {"radar_heart_rate_bpm": 120.0})]
    with_resp = [(NOW - 2.0, _sample(motion=False) | {"radar_respiratory_rate": 14.0, "radar_heart_rate_bpm": 120.0})]

    assert _build(LiveSnapshotEngine(), heart_only)["vitals"] == {
        "respiratory_rate": None,
        "heart_rate_bpm": None,
        "age_s": None,
        "caveat": "rough radar estimate",
    }
    assert _build(LiveSnapshotEngine(), with_resp)["vitals"] == {
        "respiratory_rate": 14.0,
        "heart_rate_bpm": 120.0,
        "age_s": 2.0,
        "caveat": "rough radar estimate",
    }


def test_arousal_score_bounds_and_null_cases() -> None:
    crying = _build(LiveSnapshotEngine(), _sleep_history(), alerts=_alerts(True, score=2.0))
    not_detected = _build(LiveSnapshotEngine(), [(NOW - 2.0, _sample(present=None, motion=False))])
    unreliable = LiveSnapshotEngine()
    _build(unreliable, _sleep_history(NOW), camera_age=9.0)
    sensor_unreliable = _build(unreliable, _sleep_history(NOW + 1), now=NOW + 1, camera_age=9.0)

    assert crying["arousal_score"] == 1.0
    assert not_detected["arousal_score"] is None
    assert sensor_unreliable["arousal_score"] is None


def test_signal_ages_and_schema_contract() -> None:
    history = [
        (NOW - 10.0, {"room_temperature_c": 19.2}),
        (NOW - 7.0, {"motion_detected": False}),
        (NOW - 5.0, {"room_humidity_pct": 51.0}),
        (NOW - 3.0, {"radar_respiratory_rate": 14.0}),
        (NOW - 2.0, {"person_present": True, "target_count": 1, "target_distance_cm": 75.0}),
    ]
    snapshot = _build(LiveSnapshotEngine(), history)

    assert set(snapshot) == TOP_KEYS
    assert 1 <= len(snapshot["evidence"]) <= 8
    assert snapshot["recommended_action"]["key"] in ACTION_KEYS
    assert snapshot["room"]["temperature_c"]["age_s"] == 10.0
    assert snapshot["room"]["humidity_pct"]["age_s"] == 5.0
    assert snapshot["presence"]["age_s"] == 2.0
    assert snapshot["motion"]["age_s"] == 7.0
    assert snapshot["vitals"]["age_s"] == 3.0
    assert snapshot["schema_version"] == 1


def test_language_policy_for_state_labels_actions_and_evidence() -> None:
    banned = re.compile(r"\b(safe|healthy|fine|normal|ok|okay|good|stable|asleep|sleeping|slept|likely|calm)\b", re.I)
    engines_and_histories = [
        (LiveSnapshotEngine(), _sleep_history(), _alerts(True)),
        (LiveSnapshotEngine(), [(NOW - 2.0, _sample(present=None, motion=False))], _alerts(False)),
        (LiveSnapshotEngine(), [(NOW - 2.0, _sample(target=False, motion=False))], _alerts(False)),
        (LiveSnapshotEngine(), [(NOW - 80.0, _sample(motion=False)), (NOW - 70.0, _sample(motion=True)), (NOW - 2.0, _sample(motion=False))], _alerts(False)),
        (LiveSnapshotEngine(), _sleep_history(), _alerts(False)),
        (LiveSnapshotEngine(), [(NOW - 220.0, _sample(motion=False)), (NOW - 200.0, _sample(motion=True)), (NOW - 2.0, _sample(motion=False))], _alerts(False)),
        (LiveSnapshotEngine(), [(NOW - 2.0, _sample(motion=None))], _alerts(False)),
    ]

    snapshots = [_build(engine, history, alerts=alerts) for engine, history, alerts in engines_and_histories]
    unreliable = LiveSnapshotEngine()
    _build(unreliable, _sleep_history(NOW), camera_age=9.0)
    snapshots.append(_build(unreliable, _sleep_history(NOW + 1), now=NOW + 1, camera_age=9.0))

    for snapshot in snapshots:
        texts = [
            snapshot["label"],
            snapshot["recommended_action"]["label"],
            snapshot["recommended_action"]["detail"],
            *(item["label"] for item in snapshot["evidence"]),
        ]
        assert not any(banned.search(str(text)) for text in texts)
        if snapshot["baby_state"] == "crying":
            assert not re.search(r"%|probability|chance|likely|certain", " ".join(map(str, texts)), re.I)
