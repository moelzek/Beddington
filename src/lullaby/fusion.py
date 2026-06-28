"""Motion→listen fusion.

When the sensors see movement or a present person, open a short window of
heightened sound attention so the non-cry sound diary "listens harder" (classifies
every window, at a lower confidence threshold) for a coo/fuss/stir it might
otherwise miss.

Deterministic and strictly additive: it only sharpens the *sound diary*. The cry
alarm stays on its own fixed, deterministic threshold (the safety reflex owns the
alarm), so fusion can never change *when* an alert fires.
"""

from __future__ import annotations


def has_activity(readings: dict[str, object]) -> bool:
    """True if the latest sensor reading shows movement or a present person."""
    return (
        readings.get("motion_detected") is True
        or readings.get("person_present") is True
    )


class FocusTracker:
    """A window of heightened sound attention, opened by movement/presence and
    held for ``hold_seconds`` after the most recent activity."""

    def __init__(self, hold_seconds: float = 12.0) -> None:
        self.hold_seconds = hold_seconds
        self._until: float | None = None

    def update(self, offset_seconds: float, readings: dict[str, object]) -> str:
        """Feed a sensor reading at ``offset_seconds``. Returns ``"opened"`` when
        focus has just started, ``"held"`` while it stays open, or ``"idle"``."""
        was_focused = self.focused(offset_seconds)
        if has_activity(readings):
            self._until = offset_seconds + self.hold_seconds
            return "held" if was_focused else "opened"
        return "held" if was_focused else "idle"

    def focused(self, offset_seconds: float) -> bool:
        return self._until is not None and offset_seconds < self._until
