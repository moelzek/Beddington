from datetime import UTC, datetime

from beddington.config import DetectionConfig
from beddington.state import CryEventTracker


def _tracker(**overrides: float) -> CryEventTracker:
    values = {
        "threshold": 0.4,
        "sustained_seconds": 1.0,
        "release_seconds": 0.5,
        "notification_cooldown_seconds": 30.0,
    }
    values.update(overrides)
    return CryEventTracker(
        DetectionConfig(**values), datetime(2026, 6, 18, tzinfo=UTC)
    )


def test_short_blip_does_not_become_an_event() -> None:
    tracker = _tracker(sustained_seconds=2.0)
    events = []
    for offset, score in [(0.0, 0.8), (0.4875, 0.1), (0.975, 0.1)]:
        events.extend(tracker.observe(offset, score).events)

    assert events == []


def test_sustained_cry_starts_notifies_once_and_ends() -> None:
    tracker = _tracker()
    results = [
        tracker.observe(0.0, 0.8),
        tracker.observe(0.4875, 0.9),
        tracker.observe(0.975, 0.7),
        tracker.observe(1.4625, 0.1),
        tracker.observe(1.95, 0.1),
    ]
    events = [event for result in results for event in result.events]

    assert [event.kind for event in events] == ["cry_started", "cry_ended"]
    assert sum(result.notify for result in results) == 1
    assert events[1].duration_seconds is not None
    assert events[1].duration_seconds > 0


def test_notification_cooldown_suppresses_second_episode() -> None:
    tracker = _tracker(notification_cooldown_seconds=60.0)
    notifications = 0
    for offset, score in [
        (0.0, 0.9),
        (0.4875, 0.9),
        (0.975, 0.1),
        (1.4625, 0.1),
        (2.0, 0.9),
        (2.4875, 0.9),
    ]:
        notifications += int(tracker.observe(offset, score).notify)

    assert notifications == 1
