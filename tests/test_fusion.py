from __future__ import annotations

from beddington.fusion import FocusTracker, has_activity


def test_has_activity() -> None:
    assert has_activity({"motion_detected": True})
    assert has_activity({"person_present": True})
    assert not has_activity({"motion_detected": False, "person_present": False})
    assert not has_activity({})


def test_focus_tracker_opens_holds_and_expires() -> None:
    focus = FocusTracker(hold_seconds=10.0)
    assert focus.update(0.0, {}) == "idle"
    assert not focus.focused(0.0)

    assert focus.update(5.0, {"motion_detected": True}) == "opened"
    assert focus.focused(5.0)
    assert focus.focused(14.9)  # within the hold window
    assert not focus.focused(15.0)  # 5 + 10 expired


def test_focus_tracker_extends_on_new_activity() -> None:
    focus = FocusTracker(hold_seconds=10.0)
    focus.update(5.0, {"motion_detected": True})  # opens, until 15
    # fresh activity while still focused extends the window, no re-open
    assert focus.update(12.0, {"person_present": True}) == "held"
    assert focus.focused(21.9)  # 12 + 10
    assert not focus.focused(22.0)


def test_focus_tracker_idle_without_activity() -> None:
    focus = FocusTracker()
    assert focus.update(1.0, {"motion_detected": False}) == "idle"
    assert focus.update(2.0, {}) == "idle"
    assert not focus.focused(2.0)
