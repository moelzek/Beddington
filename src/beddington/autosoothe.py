"""Auto-soothe: the assistant listens for sustained crying and, when enabled,
automatically plays a pre-chosen soothe sound.

Two pieces live here:
  * a small shared state file ({enabled, preset}) the dashboard writes and the
    always-on assistant loop reads, so the toggle crosses processes; and
  * ``CryWatcher`` — wraps the cry detector + the deterministic CryEventTracker
    and decides when a *sustained* cry warrants soothing, with a cooldown so it
    doesn't retrigger while already comforting.

The cry decision stays deterministic (the same CryEventTracker as the monitor),
so auto-soothe is reliable, and it is OFF by default.
"""

from __future__ import annotations

import json
import os
import tempfile

DEFAULT_STATE_PATH = os.path.expanduser("~/.config/beddington/autosoothe.json")


def read_state(path: str = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Return {'enabled': bool, 'preset': str}. Missing/garbled file -> disabled."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"enabled": False, "preset": ""}
    if not isinstance(data, dict):
        return {"enabled": False, "preset": ""}
    return {
        "enabled": bool(data.get("enabled")),
        "preset": str(data.get("preset") or ""),
    }


def write_state(
    enabled: bool, preset: str, path: str = DEFAULT_STATE_PATH
) -> dict[str, object]:
    """Persist the auto-soothe state atomically. Returns the written state."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    state = {"enabled": bool(enabled), "preset": str(preset or "")}
    # Unique temp in the same directory so concurrent writers (dashboard +
    # assistant) never clobber a shared ".tmp"; flush+fsync before the atomic
    # replace so a power loss can't leave a zero-length/partial state behind.
    fd, tmp = tempfile.mkstemp(
        # Same directory as the target (".", not the system temp) so os.replace
        # stays atomic on one filesystem even when path has no dir component.
        dir=directory or ".",
        prefix=".autosoothe-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return state


class CryWatcher:
    """Decides when sustained crying should trigger an auto-soothe.

    ``detector.score(samples) -> float`` and ``tracker.observe(offset, score)``
    (a CryEventTracker, whose result ``.notify`` flags sustained crying). A
    cooldown stops it retriggering while a soothe is already playing.
    """

    def __init__(self, detector: object, tracker: object, cooldown_seconds: float = 45.0) -> None:
        self._detector = detector
        self._tracker = tracker
        self._cooldown = cooldown_seconds
        self._last_trigger: float | None = None
        self.last_score = 0.0

    def observe(self, offset_seconds: float, samples: object) -> bool:
        """Feed ~1s of 16 kHz audio. Returns True when a soothe should start."""
        score = self._detector.score(samples)  # type: ignore[attr-defined]
        self.last_score = float(score)
        if not self._tracker.observe(offset_seconds, score).notify:  # type: ignore[attr-defined]
            return False
        if (
            self._last_trigger is None
            or offset_seconds - self._last_trigger >= self._cooldown
        ):
            self._last_trigger = offset_seconds
            return True
        return False
