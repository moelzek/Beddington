from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import NightReport


@dataclass(frozen=True)
class OutputPaths:
    events_json: Path
    readable_log: Path
    digest: Path


def write_outputs(output_dir: Path, report: NightReport, digest: str) -> OutputPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = OutputPaths(
        events_json=output_dir / "events.json",
        readable_log=output_dir / "night-log.txt",
        digest=output_dir / "morning-digest.txt",
    )
    paths.events_json.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    paths.readable_log.write_text(_readable_log(report), encoding="utf-8")
    paths.digest.write_text(digest.strip() + "\n", encoding="utf-8")
    return paths


def _readable_log(report: NightReport) -> str:
    lines = [
        "Lullaby night log",
        f"Source: {report.source}",
        f"Started: {report.started_at.isoformat()}",
        f"Detector: {report.detector}",
        (
            f"Threshold: {report.threshold:.3f}; "
            f"sustained: {report.sustained_seconds:.2f}s"
        ),
        "",
    ]
    if not report.events:
        lines.append("No sustained crying events detected.")
    for event in report.events:
        at = f"+{event.offset_seconds:07.2f}s"
        if event.kind == "cry_started":
            lines.append(
                f"{at}  CRY STARTED  peak model score {event.score or 0.0:.3f}"
            )
        elif event.kind == "cry_ended":
            lines.append(
                f"{at}  CRY ENDED    duration {event.duration_seconds or 0.0:.2f}s"
            )
        elif event.kind == "notification_sent":
            targets = ", ".join(
                key for key, sent in event.details.items() if sent
            ) or "none"
            lines.append(f"{at}  NOTIFIED     {targets}")
    lines.extend(
        [
            "",
            f"Windows analysed: {report.windows_processed}",
            f"Peak baby-cry model score: {report.peak_score:.3f}",
            "YAMNet scores are uncalibrated model scores, not medical probabilities.",
        ]
    )
    return "\n".join(lines) + "\n"
