"""Tests for Lullaby's deterministic local monitor."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lullaby import AttentionNeeded, ConditionCleared, LullabyMonitor, MonitorPolicy, Observation


def _alerts(events):
    return [e for e in events if isinstance(e, AttentionNeeded)]


def _clears(events):
    return [e for e in events if isinstance(e, ConditionCleared)]


def test_crying_alert_fires_only_after_configured_duration():
    monitor = LullabyMonitor(MonitorPolicy(crying_seconds=30))
    assert _alerts(monitor.update(Observation(sound="crying"), now=0)) == []
    assert _alerts(monitor.update(Observation(sound="crying"), now=29)) == []
    alerts = _alerts(monitor.update(Observation(sound="crying"), now=30))
    assert len(alerts) == 1
    assert alerts[0].condition == "crying"


def test_persistent_condition_does_not_double_alert():
    monitor = LullabyMonitor(MonitorPolicy(crying_seconds=10))
    monitor.update(Observation(sound="crying"), now=0)
    assert len(_alerts(monitor.update(Observation(sound="crying"), now=10))) == 1
    assert _alerts(monitor.update(Observation(sound="crying"), now=30)) == []


def test_view_blocked_alert_uses_its_own_threshold():
    monitor = LullabyMonitor(MonitorPolicy(view_blocked_seconds=5))
    monitor.update(Observation(view_clear=False), now=100)
    alerts = _alerts(monitor.update(Observation(view_clear=False), now=105))
    assert len(alerts) == 1
    assert alerts[0].condition == "view_blocked"


def test_condition_clear_is_logged_when_observation_returns_to_normal():
    monitor = LullabyMonitor(MonitorPolicy(crying_seconds=10))
    monitor.update(Observation(sound="crying"), now=0)
    monitor.update(Observation(sound="crying"), now=10)
    clears = _clears(monitor.update(Observation(sound="quiet"), now=15))
    assert len(clears) == 1
    assert clears[0].condition == "crying"


def test_alert_copy_does_not_make_medical_or_safety_claims():
    monitor = LullabyMonitor(MonitorPolicy(crying_seconds=0))
    alert = _alerts(monitor.update(Observation(sound="crying"), now=0))[0]
    message = alert.message().lower()
    banned = ["diagnose", "treat", "sids", "breathing health", "safe", "all clear"]
    assert all(word not in message for word in banned)


if __name__ == "__main__":
    import traceback

    failed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
