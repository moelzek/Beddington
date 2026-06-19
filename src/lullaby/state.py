from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .audio import WINDOW_SECONDS
from .config import DetectionConfig
from .models import Event


@dataclass(frozen=True)
class TrackerResult:
    events: tuple[Event, ...] = ()
    notify: bool = False


class CryEventTracker:
    def __init__(self, config: DetectionConfig, started_at: datetime):
        self.config = config
        self.started_at = started_at
        self._candidate_start: float | None = None
        self._active_start: float | None = None
        self._below_start: float | None = None
        self._peak_score = 0.0
        self._last_notification_offset: float | None = None

    def observe(self, offset_seconds: float, score: float) -> TrackerResult:
        if score >= self.config.threshold:
            return self._observe_above(offset_seconds, score)
        return self._observe_below(offset_seconds)

    def finish(self, end_offset_seconds: float) -> tuple[Event, ...]:
        if self._active_start is None:
            return ()
        event = self._end_event(max(self._active_start, end_offset_seconds))
        self._reset()
        return (event,)

    def _observe_above(self, offset: float, score: float) -> TrackerResult:
        self._below_start = None
        self._peak_score = max(self._peak_score, score)
        if self._active_start is not None:
            return TrackerResult()

        if self._candidate_start is None:
            self._candidate_start = offset
        observed = offset + WINDOW_SECONDS - self._candidate_start
        if observed < self.config.sustained_seconds:
            return TrackerResult()

        self._active_start = self._candidate_start
        event = Event(
            kind="cry_started",
            occurred_at=self._at(self._active_start),
            offset_seconds=self._active_start,
            score=self._peak_score,
            details={"label": "Baby cry, infant cry"},
        )
        notify = self._notification_due(offset)
        if notify:
            self._last_notification_offset = offset
        return TrackerResult((event,), notify)

    def _observe_below(self, offset: float) -> TrackerResult:
        if self._active_start is None:
            self._candidate_start = None
            self._peak_score = 0.0
            return TrackerResult()

        if self._below_start is None:
            self._below_start = offset
        observed_below = offset + WINDOW_SECONDS - self._below_start
        if observed_below < self.config.release_seconds:
            return TrackerResult()

        event = self._end_event(self._below_start)
        self._reset()
        return TrackerResult((event,))

    def _notification_due(self, offset: float) -> bool:
        if self._last_notification_offset is None:
            return True
        return (
            offset - self._last_notification_offset
            >= self.config.notification_cooldown_seconds
        )

    def _end_event(self, end_offset: float) -> Event:
        assert self._active_start is not None
        return Event(
            kind="cry_ended",
            occurred_at=self._at(end_offset),
            offset_seconds=end_offset,
            score=self._peak_score,
            duration_seconds=max(0.0, end_offset - self._active_start),
        )

    def _at(self, offset: float) -> datetime:
        return self.started_at + timedelta(seconds=offset)

    def _reset(self) -> None:
        self._candidate_start = None
        self._active_start = None
        self._below_start = None
        self._peak_score = 0.0
