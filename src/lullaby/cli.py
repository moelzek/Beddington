from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .audio import (
    MicrophoneAudioSource,
    RealtimeWavFileAudioSource,
    WavFileAudioSource,
)
from .config import AppConfig, SootheStepConfig, load_config
from .detector import YamNetTFLiteDetector, ensure_model
from .digest import build_digest
from .llm import polish_digest
from .models import Event, NightReport
from .narrator import narrate, speak
from .notifications import LocalNotifier
from .pipeline import run_pipeline
from .soothe import build_soothe_player
from .video import (
    capture_rpicam_still,
    capture_rpicam_visual_change,
    compare_frames,
    inspect_image_file,
    write_camera_smoke_report,
    write_visual_change_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lullaby",
        description="Local baby-cry events, night logs, and morning digests.",
    )
    parser.add_argument("--config", type=Path, help="TOML config file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyse a WAV file")
    analyze.add_argument("wav", type=Path)
    analyze.add_argument(
        "--realtime",
        action="store_true",
        help="Feed the WAV through the pipeline at real-time pace (live-style demo)",
    )
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
    change = subparsers.add_parser(
        "visual-change",
        help="Compare two local PGM/PPM frames and write derived change metrics",
    )
    change.add_argument("--before", type=Path, required=True)
    change.add_argument("--after", type=Path, required=True)
    change.add_argument("--output", type=Path, default=Path("output/visual-change"))
    change.add_argument("--pixel-threshold", type=float, default=0.08)
    change.add_argument("--changed-ratio-threshold", type=float, default=0.02)
    camera_change = subparsers.add_parser(
        "camera-change",
        help="Capture two local Pi camera frames and write derived change metrics",
    )
    camera_change.add_argument("--output", type=Path, default=Path("output/camera-change"))
    camera_change.add_argument("--width", type=int, default=160)
    camera_change.add_argument("--height", type=int, default=120)
    camera_change.add_argument("--timeout", type=float, default=1.0)
    camera_change.add_argument("--interval", type=float, default=0.5)
    camera_change.add_argument("--pixel-threshold", type=float, default=0.08)
    camera_change.add_argument("--changed-ratio-threshold", type=float, default=0.02)
    camera_change.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep the two raw BMP test frames locally in the output directory",
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
        "--speak",
        action="store_true",
        help="Run the optional local narrator after analysis and speak it if possible",
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
    if args.command == "visual-change":
        return _visual_change_command(args)
    if args.command == "camera-change":
        return _camera_change_command(args)

    detector = YamNetTFLiteDetector(args.model)
    if args.soothe:
        config = replace(config, soothe=replace(config.soothe, enabled=True))
    notifier = LocalNotifier(desktop=config.notifications.desktop and not args.no_desktop)
    if args.command == "analyze":
        if not args.wav.exists():
            raise SystemExit(f"WAV file not found: {args.wav}")
        source = (
            RealtimeWavFileAudioSource(args.wav)
            if getattr(args, "realtime", False)
            else WavFileAudioSource(args.wav)
        )
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
    spoken_text = result.digest
    narrator_config = config.narrator
    if args.speak:
        narrator_config = replace(narrator_config, enabled=True, voice_enabled=True)
    if narrator_config.enabled:
        spoken_text = narrate(result.report, narrator_config, build_digest(result.report))
        if narrator_config.voice_enabled:
            speak(spoken_text, narrator_config)
    print()
    print(spoken_text)
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


def _visual_change_command(args: argparse.Namespace) -> int:
    if not args.before.exists():
        raise SystemExit(f"Before frame not found: {args.before}")
    if not args.after.exists():
        raise SystemExit(f"After frame not found: {args.after}")
    if not 0.0 <= args.pixel_threshold <= 1.0:
        raise SystemExit("--pixel-threshold must be between 0 and 1")
    if not 0.0 <= args.changed_ratio_threshold <= 1.0:
        raise SystemExit("--changed-ratio-threshold must be between 0 and 1")

    report = compare_frames(
        args.before,
        args.after,
        pixel_threshold=args.pixel_threshold,
        changed_ratio_threshold=args.changed_ratio_threshold,
    )
    report_path = write_visual_change_report(args.output, report)

    print(f"Observation: {report.observation}")
    print(f"Mean absolute difference: {report.mean_absolute_difference:.4f}")
    print(f"Changed pixel ratio: {report.changed_pixel_ratio:.4f}")
    print("This is a local visual-change metric only, not a safety assessment.")
    print(f"Report: {report_path}")
    return 0


def _camera_change_command(args: argparse.Namespace) -> int:
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("--width and --height must be positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.interval < 0:
        raise SystemExit("--interval must be non-negative")
    if not 0.0 <= args.pixel_threshold <= 1.0:
        raise SystemExit("--pixel-threshold must be between 0 and 1")
    if not 0.0 <= args.changed_ratio_threshold <= 1.0:
        raise SystemExit("--changed-ratio-threshold must be between 0 and 1")

    report = capture_rpicam_visual_change(
        args.output,
        width=args.width,
        height=args.height,
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
        pixel_threshold=args.pixel_threshold,
        changed_ratio_threshold=args.changed_ratio_threshold,
        keep_frames=args.keep_frames,
    )
    report_path = write_visual_change_report(args.output, report)

    print(f"Observation: {report.observation}")
    print(f"Mean absolute difference: {report.mean_absolute_difference:.4f}")
    print(f"Changed pixel ratio: {report.changed_pixel_ratio:.4f}")
    if report.camera_summary:
        print(f"Camera: {report.camera_summary}")
    if report.raw_frames_retained:
        print("Raw camera frames retained locally:")
        for path in report.retained_frame_paths:
            print(f"- {path}")
        print("Do not commit or copy raw nursery frames off-device.")
    else:
        print("Raw camera frames deleted after metadata check.")
    if report.warnings:
        print(f"Warnings: {' | '.join(report.warnings[:2])}")
    print("This is a local visual-change metric only, not a safety assessment.")
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
