"""The runtime wiring: perceivers (frame -> Observation), act sinks (notebook +
live flag), and the Witness loop that ties them to the StepMachine.

Mirrors the v0 architecture (build-doc §3):

    Camera -> Perception -> State machine -> Decision -> [Notion | live flag]

The StepMachine (protocol.py) is the state machine + decision. This module is the
perception and act layers, with clean seams the CV dev and the Notion connector
fill in. Swap the Perceiver without touching the loop.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional
from typing import Protocol as Interface
from typing import runtime_checkable

from .protocol import (
    Observation,
    Protocol,
    StepEnded,
    StepMachine,
    StepStarted,
    TimingDeviation,
)


# --- perception: frame in, Observation out ------------------------------------


@runtime_checkable
class Perceiver(Interface):
    """Frame in, Observation out. The one seam every perception backend implements."""

    def observe(self, frame: bytes) -> Observation:
        ...


class MockPerceiver:
    """Replays a scripted list of step ids — for the demo and tests. No camera/model."""

    def __init__(self, script: Iterable[Optional[str]]):
        self._script = list(script)
        self._i = 0

    def observe(self, frame: bytes = b"") -> Observation:
        step_id = self._script[self._i] if self._i < len(self._script) else None
        self._i += 1
        return Observation(step_id=step_id, active=step_id is not None, confidence=1.0)


class BrainPerceiver:
    """Perceives the current step from a real camera frame using hatch-brain's
    ``Brain.decide()`` — one whitelist action per protocol step, with the protocol's
    policy as the instruction. hatch-brain's per-action debounce confirms a step
    before the machine acts on it, so a flicker can't jump the sequence.

    Needs ``hatch-brain`` (a declared dependency); imported lazily so the protocol
    machine, the mock demo, and the tests all run without it installed.
    """

    def __init__(self, protocol: Protocol, *, api_key: Optional[str] = None, **brain_kwargs):
        try:
            from hatch_brain import Brain
        except ImportError as err:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "BrainPerceiver needs hatch-brain. Install it:\n"
                "  pip install -e ../hatch/brain        # local dev\n"
                "  pip install 'hatch-brain @ git+https://github.com/moelzek/hatch.git#subdirectory=brain'\n"
                "Merge hatch PR #1 first — it has the per-action persistence fix this relies on."
            ) from err
        self._protocol = protocol
        self._brain = Brain(
            api_key=api_key,
            actions=tuple(s.id for s in protocol.steps),
            **brain_kwargs,
        )

    def observe(self, frame: bytes) -> Observation:
        d = self._brain.decide(frame, self._protocol.policy())
        step_id = None if d.action == "none" else d.action
        return Observation(step_id=step_id, active=step_id is not None, confidence=d.confidence)


# The v0 classical-CV path is the CV dev's to own: detect the high-contrast labware
# (rack, tips, reservoir, tubes), map positions to the current step id, return an
# Observation. The Perceiver interface above is the whole contract to build to —
# drop an `OpenCVPerceiver` in here and nothing else changes.


# --- act: notebook + live flag ------------------------------------------------


@runtime_checkable
class Notebook(Interface):
    def entry(self, text: str, at: float) -> None:
        ...


@runtime_checkable
class Flag(Interface):
    def alert(self, message: str) -> None:
        ...


class ConsoleNotebook:
    """Prints timestamped entries — stands in for the Notion write during the demo."""

    def entry(self, text: str, at: float) -> None:
        print(f"  [notebook {at:7.1f}s] {text}")


class ConsoleFlag:
    """Prints a loud line — stands in for the on-screen banner / LED / buzzer."""

    def alert(self, message: str) -> None:
        print(f"  /!\\ DEVIATION: {message}")


class NotionNotebook:  # pragma: no cover - stub
    """Stub for the real Notion write (model it on Mo's Granola->Notion pipeline).
    Kept out of the v0 code path until the connector + creds are wired (see agents.md)."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "NotionNotebook is a stub — wire the Notion connector before using it."
        )


# --- the loop -----------------------------------------------------------------


class Witness:
    """The loop: frame -> perceive -> step machine -> notebook + live flag."""

    def __init__(
        self,
        protocol: Protocol,
        perceiver: Perceiver,
        *,
        notebook: Notebook,
        flag: Flag,
        clock=time.monotonic,
    ):
        self.machine = StepMachine(protocol, clock=clock)
        self.perceiver = perceiver
        self.notebook = notebook
        self.flag = flag

    def step(self, frame: bytes, now: Optional[float] = None) -> None:
        observation = self.perceiver.observe(frame)
        for event in self.machine.update(observation, now=now):
            self._route(event)

    def finish(self, now: Optional[float] = None) -> None:
        for event in self.machine.finish(now=now):
            self._route(event)

    def _route(self, event) -> None:
        if isinstance(event, StepStarted):
            self.notebook.entry(f"Started: {event.step.label}", event.at)
        elif isinstance(event, StepEnded):
            self.notebook.entry(f"Finished: {event.step.label} ({event.duration:.0f}s)", event.at)
        elif isinstance(event, TimingDeviation):
            self.flag.alert(event.message())
