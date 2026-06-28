from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(frozen=True)
class AudioWindow:
    offset_seconds: float
    samples: np.ndarray


@dataclass(frozen=True)
class Event:
    kind: str
    occurred_at: datetime
    offset_seconds: float
    score: float | None = None
    duration_seconds: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["occurred_at"] = self.occurred_at.isoformat()
        return value


@dataclass(frozen=True)
class NightReport:
    started_at: datetime
    finished_at: datetime
    source: str
    detector: str
    threshold: float
    sustained_seconds: float
    windows_processed: int
    peak_score: float
    events: tuple[Event, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "source": self.source,
            "detector": self.detector,
            "threshold": self.threshold,
            "sustained_seconds": self.sustained_seconds,
            "windows_processed": self.windows_processed,
            "peak_score": self.peak_score,
            "events": [event.to_dict() for event in self.events],
        }
