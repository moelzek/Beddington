"""Derived "scene" context fused from more than one sensor.

These are best-guess, non-medical interpretations of raw readings (e.g. the
radar's focused presence vs the PIR's wide-area movement). They are observers
only: they never drive cry detection, timing, soothing, or alerts.
"""

from __future__ import annotations


def describe_presence_scene(
    person_present: object,
    motion_detected: object,
) -> str | None:
    """Fuse radar presence (focused, near the cot) with PIR movement (wide room).

    Returns a short best-guess phrase, or None when neither sensor reported.
    """
    radar = person_present if isinstance(person_present, bool) else None
    pir = motion_detected if isinstance(motion_detected, bool) else None

    if radar is None and pir is None:
        return None

    if radar is True:
        if pir is True:
            return "active near the cot"
        if pir is False:
            return "settled near the cot"
        return "present near the cot"

    if radar is False:
        if pir is True:
            return "movement elsewhere in the room, not at the cot"
        if pir is False:
            return "quiet — no one detected near the cot or in the room"
        return "no one detected near the cot"

    # Radar unknown — PIR only (wide-area movement).
    return "movement in the room" if pir else "room still"
