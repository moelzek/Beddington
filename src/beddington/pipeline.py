from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .audio import AudioSource
from .child_profile import CHILD_NAME
from .config import AppConfig
from .detector import CryDetector, dominant_baby_sound
from .digest import build_digest
from .fusion import FocusTracker
from .llm import polish_digest
from .logging import OutputPaths, write_outputs
from .models import Event, NightReport
from .notifications import Notifier
from .sensors import SensorReader
from .soothe import SoothePlayer, build_soothe_player, SootheController
from .soothe_memory import Outcome
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
    soothe_outcomes: Sequence[Outcome] = (),
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
    if sensor_sample_interval <= 0:
        raise ValueError("sensors.sample_interval_seconds must be positive")
    next_sensor_sample_offset = 0.0
    # Motion→listen: sharpen the sound diary while the sensors see activity. Only
    # active when we have both sensors and a sound classifier.
    focus = (
        FocusTracker()
        if (sound_classifier is not None and sensor_readers)
        else None
    )
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
            soothe_outcomes=soothe_outcomes,
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
                "Beddington",
                message + f"(model score {score:.2f}). Please check {CHILD_NAME}.",
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
        is_sample = (
            sensor_readers or sound_classifier is not None
        ) and window.offset_seconds + 1e-9 >= next_sensor_sample_offset
        occurred_at = started_at + timedelta(seconds=window.offset_seconds)
        if is_sample and sensor_readers:
            readings, sensor_faults = _read_sensor_sample(sensor_readers)
            if readings:
                events.append(
                    Event(
                        kind="environment_sample",
                        occurred_at=occurred_at,
                        offset_seconds=window.offset_seconds,
                        details=readings,
                    )
                )
            # A raised reader is a real fault (dead BME688, radar/PIR dropped off) —
            # surface it as a distinct event so "sensor down" is never mistaken for
            # a calm nursery. An empty {} reading (not a raise) is NOT a fault.
            if sensor_faults:
                events.append(
                    Event(
                        kind="sensor_unavailable",
                        occurred_at=occurred_at,
                        offset_seconds=window.offset_seconds,
                        details={"failures": sensor_faults},
                    )
                )
            if focus is not None and (
                focus.update(window.offset_seconds, readings) == "opened"
            ):
                reason = (
                    "movement" if readings.get("motion_detected") is True else "presence"
                )
                events.append(
                    Event(
                        kind="focused_listen",
                        occurred_at=occurred_at,
                        offset_seconds=window.offset_seconds,
                        details={"reason": reason},
                    )
                )
        # While focused, classify EVERY window (not just sample ticks) at a lower
        # threshold — "listen harder". The cry alarm above is untouched.
        focused = focus is not None and focus.focused(window.offset_seconds)
        if sound_classifier is not None and (is_sample or focused):
            threshold = config.sounds.threshold * (0.75 if focused else 1.0)
            sound = _classify_window_sound(sound_classifier, window.samples, threshold)
            if sound is not None:
                details: dict[str, object] = {"sound": sound}
                if focused:
                    details["focused"] = True  # only on the focused path; keeps the
                    # plain sound-diary schema unchanged when there are no sensors
                events.append(
                    Event(
                        kind="sound_observed",
                        occurred_at=occurred_at,
                        offset_seconds=window.offset_seconds,
                        details=details,
                    )
                )
        if is_sample:
            while window.offset_seconds + 1e-9 >= next_sensor_sample_offset:
                next_sensor_sample_offset += sensor_sample_interval

    if soothe is not None:
        soothe_result = soothe.finish(source.duration_seconds, peak_score)
        events.extend(soothe_result.events)
        if soothe_result.notify:
            targets = notifier.notify(
                "Beddington",
                (
                    "Sustained crying still detected "
                    f"(model score {peak_score:.2f}). Please check {CHILD_NAME}."
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
        # Fail OPEN: an LLM polish failure (network error, missing config, or a
        # malformed response) must never discard the night's already-built
        # deterministic digest and event log. Keep the deterministic digest and
        # write outputs regardless.
        try:
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
        except Exception:  # noqa: BLE001 - keep the deterministic digest, always write
            pass
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
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Read every sensor once.

    Returns ``(readings, faults)``. A reader that *raises* is a genuine fault
    (dead/misbehaving sensor) and is recorded in ``faults`` — it is NOT the same
    as a reader that returns a legitimately empty ``{}`` (e.g. the gas-enabled
    BME688 skipping a not-ready cycle), which is silently ignored. One bad
    sensor never aborts the sweep: the loop keeps reading the others.
    """
    readings: dict[str, object] = {}
    faults: list[dict[str, str]] = []
    for reader in sensor_readers:
        try:
            data = reader.read()
        except Exception as exc:  # noqa: BLE001 - one bad sensor must not crash the loop
            reader_name = type(reader).__name__
            faults.append(
                {"reader": reader_name, "error": f"{type(exc).__name__}: {exc}"}
            )
            _warn_sensor_unavailable(reader_name, exc)
            continue
        if data:
            readings.update(data)
        # Production readers degrade a dead device to {} instead of raising (so
        # one glitch can't crash the loop); they flag a *persistent* hardware
        # failure (missing library, device won't open) as a one-shot fault the
        # first time it happens. Surface that so an unplugged sensor is not
        # mistaken for a calm nursery.
        reader_fault = _pop_reader_fault(reader)
        if reader_fault is not None:
            reader_name = type(reader).__name__
            faults.append({"reader": reader_name, "error": reader_fault})
            _warn_sensor_unavailable(reader_name, RuntimeError(reader_fault))
    return readings, faults


def _pop_reader_fault(reader: object) -> str | None:
    """Return a reader's one-shot persistent-failure message, or None.

    Readers that can't raise (they fall back to {}) expose ``pop_fault()`` which
    returns the failure once and clears it, so a dead sensor surfaces exactly
    once rather than every tick.
    """
    pop = getattr(reader, "pop_fault", None)
    if pop is None:
        return None
    try:
        fault = pop()
    except Exception:  # noqa: BLE001 - fault reporting must never crash the loop
        return None
    return str(fault) if fault else None


# Rate-limit the dead-sensor warning per reader so a persistently-dead sensor
# logs once (and then hourly), instead of spamming the console every tick.
_SENSOR_WARN_INTERVAL_SECONDS = 3600.0
_last_sensor_warn: dict[str, float] = {}


def _warn_sensor_unavailable(reader_name: str, exc: BaseException) -> None:
    now = time.monotonic()
    last = _last_sensor_warn.get(reader_name)
    if last is not None and (now - last) < _SENSOR_WARN_INTERVAL_SECONDS:
        return
    _last_sensor_warn[reader_name] = now
    logging.getLogger(__name__).warning(
        "sensor %s read failed (%s: %s) — treating as unavailable, not calm",
        reader_name,
        type(exc).__name__,
        exc,
    )
