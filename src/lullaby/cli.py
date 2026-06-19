from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .audio import MicrophoneAudioSource, WavFileAudioSource
from .config import AppConfig, load_config
from .detector import YamNetTFLiteDetector, ensure_model
from .digest import build_digest
from .llm import polish_digest
from .models import Event, NightReport
from .notifications import LocalNotifier
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lullaby",
        description="Local baby-cry events, night logs, and morning digests.",
    )
    parser.add_argument("--config", type=Path, help="TOML config file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyse a WAV file")
    analyze.add_argument("wav", type=Path)
    _add_run_options(analyze)

    listen = subparsers.add_parser("listen", help="Listen to a microphone")
    listen.add_argument("--seconds", type=float, default=60.0)
    listen.add_argument("--device")
    _add_run_options(listen)

    model = subparsers.add_parser(
        "download-model", help="Download and verify the official YAMNet TFLite model"
    )
    model.add_argument("--model", type=Path)

    digest = subparsers.add_parser(
        "digest", help="Regenerate a digest from an events.json file"
    )
    digest.add_argument("events_json", type=Path)
    digest.add_argument("--llm", action="store_true")
    digest.add_argument("--output", type=Path)
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, default=Path("output/latest"))
    parser.add_argument("--model", type=Path)
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--started-at",
        type=datetime.fromisoformat,
        help="Optional ISO timestamp for the start of the recording",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    if args.command == "download-model":
        print(ensure_model(args.model))
        return 0
    if args.command == "digest":
        return _digest_command(args, config)

    detector = YamNetTFLiteDetector(args.model)
    notifier = LocalNotifier(desktop=config.notifications.desktop and not args.no_desktop)
    if args.command == "analyze":
        if not args.wav.exists():
            raise SystemExit(f"WAV file not found: {args.wav}")
        source = WavFileAudioSource(args.wav)
    else:
        source = MicrophoneAudioSource(args.seconds, args.device)

    result = run_pipeline(
        source=source,
        detector=detector,
        notifier=notifier,
        config=config,
        output_dir=args.output,
        started_at=args.started_at,
        use_llm=args.llm,
    )
    print()
    print(result.digest)
    print()
    print(f"Events: {result.paths.events_json}")
    print(f"Readable log: {result.paths.readable_log}")
    print(f"Morning digest: {result.paths.digest}")
    return 0


def _digest_command(args: argparse.Namespace, config: AppConfig) -> int:
    raw = json.loads(args.events_json.read_text(encoding="utf-8"))
    events = tuple(
        Event(
            kind=item["kind"],
            occurred_at=datetime.fromisoformat(item["occurred_at"]),
            offset_seconds=float(item["offset_seconds"]),
            score=item.get("score"),
            duration_seconds=item.get("duration_seconds"),
            details=item.get("details", {}),
        )
        for item in raw["events"]
    )
    report = NightReport(
        started_at=datetime.fromisoformat(raw["started_at"]),
        finished_at=datetime.fromisoformat(raw["finished_at"]),
        source=raw["source"],
        detector=raw["detector"],
        threshold=float(raw["threshold"]),
        sustained_seconds=float(raw["sustained_seconds"]),
        windows_processed=int(raw["windows_processed"]),
        peak_score=float(raw["peak_score"]),
        events=events,
    )
    summary = build_digest(report)
    if args.llm:
        summary = polish_digest(
            summary,
            report,
            config.llm.__class__(
                enabled=True,
                base_url=config.llm.base_url,
                model=config.llm.model,
                api_key=config.llm.api_key,
            ),
        )
    if args.output:
        args.output.write_text(summary + "\n", encoding="utf-8")
    print(summary)
    return 0
