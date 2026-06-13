"""Lab Witness — a Pi over the bench that watches a scientist, writes the lab
notebook, and flags when reality drifts from the protocol.

Architecture (build-doc §3): Camera -> Perception -> State machine -> Decision ->
[Notion | live flag]. The perception step reuses Hatch's decision kernel
(``hatch-brain``) via ``BrainPerceiver``; the timing state machine and act layer
are Lab Witness's own.
"""

from .protocol import (
    Observation,
    Protocol,
    Step,
    StepEnded,
    StepMachine,
    StepStarted,
    TimingDeviation,
)
from .runtime import (
    BrainPerceiver,
    ConsoleFlag,
    ConsoleNotebook,
    Flag,
    MockPerceiver,
    Notebook,
    NotionNotebook,
    Perceiver,
    Witness,
)

__version__ = "0.0.1"

__all__ = [
    "Protocol",
    "Step",
    "StepMachine",
    "Observation",
    "StepStarted",
    "StepEnded",
    "TimingDeviation",
    "Perceiver",
    "MockPerceiver",
    "BrainPerceiver",
    "Notebook",
    "Flag",
    "ConsoleNotebook",
    "ConsoleFlag",
    "NotionNotebook",
    "Witness",
]
