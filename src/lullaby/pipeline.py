from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .audio import AudioSource
from .config import AppConfig
from .detector import CryDetector
from .digest import build_digest
from .llm import polish_digest
from .logging import OutputPaths, write_outputs
from .models import Event, NightReport
from .notifications import Notifier
from .state import CryEventTracker


@dataclass(frozen=True)
class RunResult:
    report: NightReport
    digest: str
    paths: OutputPaths


def run_pipeline(
    source: AudioSource,
    detector: CryDetector,
    notifier: Notifier,
    config: AppConfig,
    output_dir: Path,
    started_at: datetime | None = None,
    use_llm: bool | None = None,
) -> RunResult:
    started_at = started_at or datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    tracker = CryEventTracker(config.detection, started_at)
    events: list[Event] = []
    windows_processed = 0
    peak_score = 0.0

    for window in source.windows():
        score = detector.score(window.samples)
        windows_processed += 1
        peak_score = max(peak_score, score)
        result = tracker.observe(window.offset_seconds, score)
        events.extend(result.events)
        if result.notify:
            targets = notifier.notify(
                "Lullaby",
                (
                    "Sustained crying detected "
                    f"(model score {score:.2f}). Please check the baby."
                ),
            )
            events.append(
                Event(
                    kind="notification_sent",
                    occurred_at=started_at + timedelta(seconds=window.offset_seconds),
                    offset_seconds=window.offset_seconds,
                    score=score,
                    details=targets,
                )
            )

    events.extend(tracker.finish(source.duration_seconds))
    finished_at = started_at + timedelta(seconds=source.duration_seconds)
    report = NightReport(
        started_at=started_at,
        finished_at=finished_at,
        source=source.name,
        detector=detector.name,
        threshold=config.detection.threshold,
        sustained_seconds=config.detection.sustained_seconds,
        windows_processed=windows_processed,
        peak_score=peak_score,
        events=tuple(events),
    )
    digest = build_digest(report)
    llm_enabled = config.llm.enabled if use_llm is None else use_llm
    if llm_enabled:
        digest = polish_digest(
            digest,
            report,
            config.llm.__class__(
                enabled=True,
                base_url=config.llm.base_url,
                model=config.llm.model,
                api_key=config.llm.api_key,
            ),
        )
    paths = write_outputs(output_dir, report, digest)
    return RunResult(report=report, digest=digest, paths=paths)
