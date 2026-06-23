from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .audio import MicrophoneAudioSource, WavFileAudioSource
from .config import AppConfig, SootheStepConfig, load_config
from .detector import YamNetTFLiteDetector, ensure_model
from .digest import build_digest
from .llm import polish_digest
from .models import Event, NightReport
from .notifications import LocalNotifier
from .pipeline import run_pipeline
from .soothe import build_soothe_player
from .video import capture_rpicam_still, inspect_image_file, write_camera_smoke_report


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

    preview = subparsers.add_parser(
        "preview-soothe", help="Play the selected soothe preset briefly"
    )
    preview.add_argument("--preset", help="Preset name from the config")
    preview.add_argument("--seconds", type=float, default=5.0)
    preview.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected preset without playing audio",
    )
    camera = subparsers.add_parser(
        "camera-smoke",
        help="Run a local camera or image metadata smoke test",
    )
    camera.add_argument(
        "--image",
        type=Path,
        help="Inspect an existing local JPEG/PNG instead of capturing from rpicam",
    )
    camera.add_argument("--output", type=Path, default=Path("output/camera-smoke"))
    camera.add_argument("--width", type=int, default=640)
    camera.add_argument("--height", type=int, default=480)
    camera.add_argument("--timeout", type=float, default=1.0)
    camera.add_argument(
        "--keep-frame",
        action="store_true",
        help="Keep the raw test frame locally in the output directory",
    )
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, default=Path("output/latest"))
    parser.add_argument("--model", type=Path)
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--soothe",
        action="store_true",
        help="Enable the selected Tier 1 soothe preset before parent notification",
    )
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
    if args.command == "preview-soothe":
        return _preview_soothe_command(args, config)
    if args.command == "camera-smoke":
        return _camera_smoke_command(args)

    detector = YamNetTFLiteDetector(args.model)
    if args.soothe:
        config = replace(config, soothe=replace(config.soothe, enabled=True))
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


def _preview_soothe_command(args: argparse.Namespace, config: AppConfig) -> int:
    if args.seconds <= 0:
        raise SystemExit("--seconds must be positive")

    preset, step = _select_soothe_step(config, args.preset)
    preview_step = replace(
        step,
        wait_seconds=args.seconds,
        play_seconds=args.seconds,
    )
    player_mode = "none" if args.dry_run else "auto"
    preview_config = replace(
        config.soothe,
        enabled=True,
        player=player_mode,
        preset=preset,
        steps=(preview_step,),
    )
    player = build_soothe_player(preview_config)
    playback = player.play(preview_step)

    print(f"Preset: {preset} ({preview_step.name})")
    print(f"Sound: {preview_step.sound_path or 'none'}")
    print(f"Seconds: {args.seconds:g}")

    if not playback.get("played"):
        reason = playback.get("reason", "unknown")
        if args.dry_run:
            print(f"Dry run: {reason}")
            return 0
        print(f"Playback did not start: {reason}")
        if reason == "no_supported_player":
            print("Install FFmpeg for ffplay, or use Raspberry Pi OS audio tools.")
        return 1

    print(f"Playback started with {playback.get('player', 'unknown')}.")
    print("Listen for low-volume audio from the selected output device.")
    try:
        time.sleep(args.seconds)
    finally:
        player.stop_all()
    print("Preview finished.")
    return 0


def _camera_smoke_command(args: argparse.Namespace) -> int:
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("--width and --height must be positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.image and args.keep_frame:
        raise SystemExit("--keep-frame is only used when capturing from rpicam")

    if args.image:
        report = inspect_image_file(args.image)
    else:
        report = capture_rpicam_still(
            args.output,
            width=args.width,
            height=args.height,
            timeout_seconds=args.timeout,
            keep_frame=args.keep_frame,
        )
    report_path = write_camera_smoke_report(args.output, report)

    print(f"Camera smoke source: {report.source}")
    print(
        f"Image metadata: {report.image.format} "
        f"{report.image.width}x{report.image.height}, {report.image.byte_count} bytes"
    )
    if report.camera_summary:
        print(f"Camera: {report.camera_summary}")
    if report.metadata_keys:
        print(f"Metadata keys: {', '.join(report.metadata_keys[:8])}")
    if report.raw_frame_retained:
        print(f"Raw test frame retained locally: {report.retained_frame_path}")
        print("Do not commit or copy raw nursery frames off-device.")
    else:
        print("Raw test frame deleted after metadata check.")
    if report.warnings:
        print(f"Warnings: {' | '.join(report.warnings)}")
    print(f"Report: {report_path}")
    return 0


def _select_soothe_step(
    config: AppConfig,
    requested_preset: str | None,
) -> tuple[str, SootheStepConfig]:
    preset = requested_preset or config.soothe.preset
    if config.soothe.presets:
        if preset not in config.soothe.presets:
            options = ", ".join(sorted(config.soothe.presets))
            raise SystemExit(
                f"Unknown soothe preset '{preset}'. Choose one of: {options}"
            )
        return preset, config.soothe.presets[preset]
    if config.soothe.steps and not requested_preset:
        return preset, config.soothe.steps[0]
    raise SystemExit("No soothe preset is configured")
