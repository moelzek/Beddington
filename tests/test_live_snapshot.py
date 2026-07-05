from __future__ import annotations

import re

from beddington.live_snapshot import LiveSnapshotEngine, SnapshotThresholds

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


def test_caregiver_present_from_sustained_multi_target_radar_only() -> None:
    history = [
        (NOW - 8.0, _sample(motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(motion=False) | {"target_count": 2}),
    ]

    snapshot = _build(LiveSnapshotEngine(), history)

    assert snapshot["baby_state"] == "caregiver_present"
    assert snapshot["label"] == "Someone's in the room — 2 radar targets"
    assert snapshot["confidence"] == {
        "band": "medium",
        "basis": "multiple radar targets; identity unknown",
    }
    assert snapshot["arousal_score"] is None
    assert snapshot["recommended_action"] == {
        "key": "none",
        "label": "No suggested action",
        "detail": "Multiple radar targets are visible in the room.",
        "evidence_signals": ["presence", "motion"],
    }
    assert any(
        item["signal"] == "target_count" and item["value"] == 2
        for item in snapshot["evidence"]
    )


def test_caregiver_present_requires_multiple_fresh_correlated_targets() -> None:
    single_target = [
        (NOW - 8.0, _sample(motion=False)),
        (NOW - 2.0, _sample(motion=False)),
    ]
    missing_target_count = [
        (NOW - 8.0, _sample(target=False, motion=False)),
        (NOW - 2.0, _sample(target=False, motion=False)),
    ]
    missing_presence = [
        (NOW - 8.0, _sample(present=None, motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(present=None, motion=False) | {"target_count": 2}),
    ]
    false_presence = [
        (NOW - 8.0, _sample(present=False, motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(present=False, motion=False) | {"target_count": 2}),
    ]
    uncorroborated_presence = [
        (NOW - 20.0, _sample(motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(target=False, motion=False)),
    ]

    for history in (
        single_target,
        missing_target_count,
        missing_presence,
        false_presence,
        uncorroborated_presence,
    ):
        assert _build(LiveSnapshotEngine(), history)["baby_state"] != "caregiver_present"


def test_caregiver_present_release_holds_then_falls_through() -> None:
    engine = LiveSnapshotEngine()
    active_history = [
        (NOW - 8.0, _sample(motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(motion=False) | {"target_count": 2}),
    ]
    assert _build(engine, active_history, now=NOW)["baby_state"] == "caregiver_present"

    held = _build(engine, [(NOW + 18.0, _sample(motion=False))], now=NOW + 20.0)
    released = _build(engine, [(NOW + 33.0, _sample(motion=False))], now=NOW + 35.0)

    assert held["baby_state"] == "caregiver_present"
    assert released["baby_state"] != "caregiver_present"

    false_engine = LiveSnapshotEngine()
    assert _build(false_engine, active_history, now=NOW)["baby_state"] == "caregiver_present"
    false_presence = _build(
        false_engine,
        [(NOW + 3.0, _sample(present=False, target=False, motion=False))],
        now=NOW + 5.0,
    )
    assert false_presence["baby_state"] != "caregiver_present"


def test_caregiver_present_loses_to_higher_precedence_states() -> None:
    history = [
        (NOW - 8.0, _sample(motion=False) | {"target_count": 2}),
        (NOW - 2.0, _sample(motion=False) | {"target_count": 2}),
    ]

    crying = _build(LiveSnapshotEngine(), history, alerts=_alerts(True))
    unreliable = _build(
        LiveSnapshotEngine(SnapshotThresholds(health_bad_checks_to_enter=1)),
        history,
        camera_age=9.0,
    )
    missing_presence = _build(
        LiveSnapshotEngine(),
        [
            (NOW - 8.0, _sample(present=None, motion=False) | {"target_count": 2}),
            (NOW - 2.0, _sample(present=None, motion=False) | {"target_count": 2}),
        ],
    )

    assert crying["baby_state"] == "crying"
    assert unreliable["baby_state"] == "sensor_unreliable"
    assert missing_presence["baby_state"] == "not_detected"


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


def _alert_of_type(snapshot: dict[str, object], alert_type: str) -> dict[str, object] | None:
    return next(
        (item for item in snapshot["alerts"] if item.get("type") == alert_type),
        None,
    )


def test_t2_room_warm_alert_uses_hysteresis_and_cooldown() -> None:
    engine = LiveSnapshotEngine()

    raised = _build(engine, [(NOW - 2.0, _sample(temp=20.2))], now=NOW)
    held = _build(engine, [(NOW - 2.0, _sample(temp=19.7))], now=NOW + 1.0)
    cleared = _build(engine, [(NOW - 2.0, _sample(temp=19.4))], now=NOW + 2.0)
    blocked = _build(engine, [(NOW - 2.0, _sample(temp=20.2))], now=NOW + 3.0)

    warm = _alert_of_type(raised, "room_warm")
    assert warm is not None
    assert warm["tier"] == "T2"
    assert warm["title"] == "Room a bit warm"
    assert warm["message"] == "Temperature 20.2°C; usual room range 16-20°C."
    assert warm["action"]["key"] == "adjust_room"
    assert warm["notification"] == {"browser": True, "sound": False}
    assert _alert_of_type(held, "room_warm")["seq"] == warm["seq"]
    assert _alert_of_type(cleared, "room_warm") is None
    assert _alert_of_type(blocked, "room_warm") is None


def test_t2_room_cool_alert() -> None:
    snapshot = _build(LiveSnapshotEngine(), [(NOW - 2.0, _sample(temp=15.8))])
    cool = _alert_of_type(snapshot, "room_cool")

    assert cool is not None
    assert cool["title"] == "Room a bit cool"
    assert cool["message"] == "Temperature 15.8°C; usual room range 16-20°C."
    assert cool["notification"]["sound"] is False


def test_t2_sensor_stale_and_camera_down_alerts_when_unreliable_latched() -> None:
    engine = LiveSnapshotEngine(SnapshotThresholds(health_bad_checks_to_enter=1))
    snapshot = _build(engine, [(NOW - 20.0, _sample(motion=False))], camera_age=9.0)

    stale = _alert_of_type(snapshot, "sensor_stale")
    camera = _alert_of_type(snapshot, "camera_down")

    assert snapshot["baby_state"] == "sensor_unreliable"
    assert stale is not None
    assert stale["action"]["key"] == "reposition_device"
    assert stale["message"] == "No fresh readings, radar, history reading for 20s."
    assert {item["signal"] for item in stale["evidence"]} == {"readings", "radar", "history"}
    assert camera is not None
    assert camera["action"]["key"] == "check_camera"
    assert camera["message"] == "No camera frame for 9s."
    assert all(
        item["notification"]["sound"] is False
        for item in snapshot["alerts"]
        if item["tier"] == "T2"
    )


def test_t2_device_restarted_active_then_expires() -> None:
    engine = LiveSnapshotEngine(
        SnapshotThresholds(device_restart_notice_s=5.0),
        process_start_ts=NOW - 1.0,
    )

    active = _build(engine, _sleep_history(NOW), now=NOW)
    expired = _build(engine, _sleep_history(NOW + 6.0), now=NOW + 6.0)

    restart = _alert_of_type(active, "device_restarted")
    assert restart is not None
    assert restart["message"] == "Readings resumed after a restart."
    assert restart["action"] == {
        "key": "none",
        "label": "No suggested action",
        "detail": "Review recent readings.",
        "evidence_signals": ["device"],
    }
    assert restart["notification"]["sound"] is False
    assert _alert_of_type(expired, "device_restarted") is None


def test_t1_item_shape_unchanged_when_t2_is_active() -> None:
    snapshot = _build(
        LiveSnapshotEngine(),
        [(NOW - 2.0, _sample(temp=20.2))],
        alerts=_alerts(True, score=0.92, age=65.0),
    )

    assert snapshot["alerts"][0] == {
        "tier": "T1",
        "type": "cry_sustained",
        "title": "Cry detected",
        "message": "cry score 0.9",
        "score": 0.92,
        "seq": 7,
        "age_s": 65.0,
        "active": True,
    }
    assert _alert_of_type(snapshot, "room_warm") is not None


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
