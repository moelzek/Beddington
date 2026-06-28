from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .audio import AudioSource
from .config import AppConfig
from .detector import CryDetector, dominant_baby_sound
from .digest import build_digest
from .llm import polish_digest
from .logging import OutputPaths, write_outputs
from .models import Event, NightReport
from .notifications import Notifier
from .sensors import SensorReader
from .soothe import SoothePlayer, build_soothe_player, SootheController
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
    soothe_player: SoothePlayer | None = None,
    sensor_readers: Sequence[SensorReader] = (),
    sound_classifier: Callable[..., dict[str, float]] | None = None,
) -> RunResult:
    started_at = started_at or datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    tracker = CryEventTracker(config.detection, started_at)
    events: list[Event] = []
    windows_processed = 0
    peak_score = 0.0
    sensor_sample_interval = config.sensors.sample_interval_seconds
    next_sensor_sample_offset = 0.0
    soothe = None
    if config.soothe.enabled:
        soothe = SootheController(
            config.soothe,
            started_at,
            soothe_player or build_soothe_player(config.soothe),
            quiet_threshold=(
                config.soothe.quiet_check.quiet_threshold
                if config.soothe.quiet_check.quiet_threshold is not None
                else config.detection.threshold
            ),
        )

    for window in source.windows():
        score = detector.score(window.samples)
        windows_processed += 1
        peak_score = max(peak_score, score)
        result = tracker.observe(window.offset_seconds, score)
        events.extend(result.events)
        notify = result.notify
        if soothe is not None:
            soothe_result = soothe.observe(
                window.offset_seconds,
                score,
                result.events,
                escalation_due=result.notify,
            )
            events.extend(soothe_result.events)
            notify = soothe_result.notify
        if notify:
            message = (
                "Sustained crying still detected "
                if soothe is not None
                else "Sustained crying detected "
            )
            targets = notifier.notify(
                "Lullaby",
                message + f"(model score {score:.2f}). Please check the baby.",
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
        if (
            (sensor_readers or sound_classifier is not None)
            and window.offset_seconds + 1e-9 >= next_sensor_sample_offset
        ):
            occurred_at = started_at + timedelta(seconds=window.offset_seconds)
            if sensor_readers:
                readings = _read_sensor_sample(sensor_readers)
                if readings:
                    events.append(
                        Event(
                            kind="environment_sample",
                            occurred_at=occurred_at,
                            offset_seconds=window.offset_seconds,
                            details=readings,
                        )
                    )
            if sound_classifier is not None:
                sound = _classify_window_sound(
                    sound_classifier, window.samples, config.sounds.threshold
                )
                if sound is not None:
                    events.append(
                        Event(
                            kind="sound_observed",
                            occurred_at=occurred_at,
                            offset_seconds=window.offset_seconds,
                            details={"sound": sound},
                        )
                    )
            while window.offset_seconds + 1e-9 >= next_sensor_sample_offset:
                next_sensor_sample_offset += sensor_sample_interval

    if soothe is not None:
        soothe_result = soothe.finish(source.duration_seconds, peak_score)
        events.extend(soothe_result.events)
        if soothe_result.notify:
            targets = notifier.notify(
                "Lullaby",
                (
                    "Sustained crying still detected "
                    f"(model score {peak_score:.2f}). Please check the baby."
                ),
            )
            events.append(
                Event(
                    kind="notification_sent",
                    occurred_at=started_at + timedelta(seconds=source.duration_seconds),
                    offset_seconds=source.duration_seconds,
                    score=peak_score,
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


def _classify_window_sound(
    classifier: Callable[..., dict[str, float]],
    samples: object,
    threshold: float,
) -> str | None:
    try:
        scores = classifier(samples)
    except Exception:
        return None
    # Crying has its own deterministic detector; this diary is non-cry sounds.
    return dominant_baby_sound(scores, threshold, exclude=("crying",))


def _read_sensor_sample(
    sensor_readers: Sequence[SensorReader],
) -> dict[str, object]:
    readings: dict[str, object] = {}
    for reader in sensor_readers:
        try:
            data = reader.read()
        except Exception:
            data = {}
        if data:
            readings.update(data)
    return readings
