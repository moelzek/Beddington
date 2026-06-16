"""The protocol state machine — Lab Witness's own layer on top of perception.

hatch-brain answers "what is happening in this frame?". This module answers the
questions that are Lab Witness's own: which ordered protocol step are we on, how
long has it taken, and has a timed step over- or under-run its window?

It is pure Python with an injected clock, so it tests deterministically — no
camera, no model, no Pi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Step:
    """One ordered step of a protocol.

    ``min_seconds`` / ``max_seconds`` define the timing window. Leave both ``None``
    for an untimed step: it is logged, but never raises a timing deviation.
    """

    id: str
    label: str
    min_seconds: Optional[float] = None
    max_seconds: Optional[float] = None

    @property
    def timed(self) -> bool:
        return self.min_seconds is not None or self.max_seconds is not None


@dataclass(frozen=True)
class Protocol:
    name: str
    steps: tuple[Step, ...]

    def policy(self) -> str:
        """A plain-English instruction for a vision model (the BrainPerceiver):
        identify which ordered step is happening right now, by id."""
        listing = "\n".join(f'- "{s.id}": {s.label}' for s in self.steps)
        return (
            f"You are watching a lab bench during this protocol: {self.name}. "
            "The steps, in order, are:\n" + listing + "\n"
            'Reply with the id of the step happening RIGHT NOW, or "none" if the '
            "bench is idle or between steps."
        )


# --- events the machine emits -------------------------------------------------


@dataclass(frozen=True)
class StepStarted:
    step: Step
    at: float


@dataclass(frozen=True)
class StepEnded:
    step: Step
    at: float
    duration: float


@dataclass(frozen=True)
class TimingDeviation:
    step: Step
    kind: str  # "over" | "under"
    duration: float  # seconds elapsed (live) or total (at end)
    window: tuple[Optional[float], Optional[float]]
    live: bool  # True = caught mid-step, the moment the over-run happened

    def message(self) -> str:
        lo, hi = (_fmt(self.window[0]), _fmt(self.window[1]))
        tag = " [live]" if self.live else ""
        if self.kind == "over":
            return f"{self.step.label}: over-run — {self.duration:.0f}s (window {lo}–{hi}s){tag}"
        return f"{self.step.label}: under-run — only {self.duration:.0f}s (window {lo}–{hi}s)"


def _fmt(v: Optional[float]) -> str:
    return "·" if v is None else f"{v:.0f}"


@dataclass
class Observation:
    """What a Perceiver reports for one frame (see runtime.py)."""

    step_id: Optional[str] = None  # the step the perceiver thinks is happening, or None
    active: bool = False
    confidence: float = 0.0


class StepMachine:
    """Walks an ordered ``Protocol``, timing each step and flagging timing deviations.

    Feed it ``Observation``s (from any Perceiver) via ``update``; it returns the list
    of events that observation triggered. It advances to the next step only when it
    sees that next step's id — v0 is one known, ordered series, and the Perceiver is
    expected to debounce flicker (hatch-brain does, per its persist_frames).
    """

    def __init__(self, protocol: Protocol, *, clock=time.monotonic):
        self.protocol = protocol
        self._clock = clock
        self._index = -1  # -1 = not started; otherwise the current step index
        self._started_at: Optional[float] = None
        self._live_over_flagged = False

    @property
    def current(self) -> Optional[Step]:
        steps = self.protocol.steps
        return steps[self._index] if 0 <= self._index < len(steps) else None

    def update(self, observation: Observation, now: Optional[float] = None) -> list:
        now = self._clock() if now is None else now
        steps = self.protocol.steps
        events: list = []

        next_index = self._index + 1
        transitioning = (
            next_index < len(steps) and observation.step_id == steps[next_index].id
        )

        if transitioning:
            events.extend(self._end_current(now))
            self._index = next_index
            self._started_at = now
            self._live_over_flagged = False
            events.append(StepStarted(steps[next_index], now))
        else:
            # Live over-run: flag it the moment it happens, not at step end.
            cur = self.current
            if (
                cur is not None
                and cur.timed
                and cur.max_seconds is not None
                and self._started_at is not None
                and not self._live_over_flagged
                and (now - self._started_at) > cur.max_seconds
            ):
                self._live_over_flagged = True
                events.append(
                    TimingDeviation(
                        cur, "over", now - self._started_at,
                        (cur.min_seconds, cur.max_seconds), live=True,
                    )
                )
        return events

    def finish(self, now: Optional[float] = None) -> list:
        """End the final step (call when the run is over)."""
        now = self._clock() if now is None else now
        events = self._end_current(now)
        self._index = len(self.protocol.steps)  # past the end
        self._started_at = None
        return events

    def _end_current(self, now: float) -> list:
        cur = self.current
        if cur is None or self._started_at is None:
            return []
        duration = now - self._started_at
        events: list = [StepEnded(cur, now, duration)]
        dev = self._deviation(cur, duration)
        if dev is not None:
            events.append(dev)
        return events

    def _deviation(self, step: Step, duration: float) -> Optional[TimingDeviation]:
        if not step.timed:
            return None
        # An over-run already caught live is not flagged again at step end.
        if (
            step.max_seconds is not None
            and duration > step.max_seconds
            and not self._live_over_flagged
        ):
            return TimingDeviation(step, "over", duration, (step.min_seconds, step.max_seconds), live=False)
        if step.min_seconds is not None and duration < step.min_seconds:
            return TimingDeviation(step, "under", duration, (step.min_seconds, step.max_seconds), live=False)
        return None
