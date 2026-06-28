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
from .assistant import answer_question
from .config import AppConfig, SootheStepConfig, load_config
from .context import describe_presence_scene
from .detector import YamNetTFLiteDetector, ensure_model
from .ears import WAKE_WORDS, extract_wake_question
from .digest import build_digest
from .llm import polish_digest
from .models import Event, NightReport
from .narrator import narrate, speak
from .notifications import LocalNotifier
from .pipeline import run_pipeline
from .radar_vitals import (
    RADAR_VITALS_DISCLAIMER,
    format_radar_reading,
    summarise_radar_vitals,
    summarise_radar_vitals_from_events,
)
from .sensors import Mr60RadarReader, build_sensor_readers
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
    radar_vitals = subparsers.add_parser(
        "radar-vitals",
        help="Bench-only: live radar readout + labelled vital-sign period summary",
    )
    radar_vitals.add_argument(
        "--host",
        help="Radar host/IP (defaults to [sensors.radar].host from the config)",
    )
    radar_vitals.add_argument("--duration", type=float, default=120.0)
    radar_vitals.add_argument("--interval", type=float, default=5.0)
    radar_vitals.add_argument(
        "--speak",
        action="store_true",
        help="Speak the labelled vitals period summary at the end",
    )
    radar_vitals.add_argument(
        "--output",
        type=Path,
        help="Optional JSON file to write the captured labelled samples to",
    )
    sensors_live = subparsers.add_parser(
        "sensors-live",
        help="Live combined readout of every enabled sensor (air, motion, radar)",
    )
    sensors_live.add_argument(
        "--host",
        help="Radar host/IP override (defaults to [sensors.radar].host)",
    )
    sensors_live.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Seconds to run; 0 (default) runs until Ctrl-C",
    )
    sensors_live.add_argument("--interval", type=float, default=3.0)
    sounds_live = subparsers.add_parser(
        "sounds-live",
        help="Live readout of what the mic hears (cooing, laughter, snoring, cry...)",
    )
    sounds_live.add_argument("--seconds", type=float, default=30.0)
    sounds_live.add_argument("--device")
    sounds_live.add_argument("--model", type=Path)
    sounds_live.add_argument(
        "--threshold",
        type=float,
        help="Min score to report a sound (defaults to [sounds].threshold)",
    )
    ask = subparsers.add_parser(
        "ask",
        help="Ask about the room; it answers from the live sensors",
    )
    ask.add_argument("question", nargs="+", help="e.g. what is the humidity")
    ask.add_argument(
        "--speak", action="store_true", help="Speak the answer aloud via the voice"
    )
    listen_assistant = subparsers.add_parser(
        "listen-assistant",
        help='Wake-word voice Q&A: say "Hi Paddington, what is the humidity?"',
    )
    listen_assistant.add_argument("--device")
    listen_assistant.add_argument(
        "--seconds", type=float, default=0.0, help="0 (default) runs until Ctrl-C"
    )
    listen_assistant.add_argument("--model-size", default="tiny.en")
    listen_assistant.add_argument("--compute-type", default="int8")
    listen_assistant.add_argument("--energy-threshold", type=float, default=0.02)
    listen_assistant.add_argument(
        "--wake-word",
        action="append",
        help="Override the wake word(s); repeatable (default: Paddington)",
    )
    listen_assistant.add_argument(
        "--no-speak", action="store_true", help="Print answers only, do not speak"
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
    if args.command == "radar-vitals":
        return _radar_vitals_command(args, config)
    if args.command == "sensors-live":
        return _sensors_live_command(args, config)
    if args.command == "sounds-live":
        return _sounds_live_command(args, config)
    if args.command == "ask":
        return _ask_command(args, config)
    if args.command == "listen-assistant":
        return _listen_assistant_command(args, config)
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
        sensor_readers=build_sensor_readers(config.sensors),
        sound_classifier=detector.classify if config.sounds.enabled else None,
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
    # Bench/research only: a separate, deterministic, clearly-labelled vitals
    # readout. It is never produced by the LLM and never mixed into the recap
    # above, so the radar's breathing/heart values can never become a product
    # claim about the baby.
    if config.sensors.radar.bench_vitals:
        vitals_summary = summarise_radar_vitals_from_events(result.report.events)
        if vitals_summary:
            print()
            print(vitals_summary)
            if narrator_config.voice_enabled:
                speak(vitals_summary, narrator_config)
    print()
    print(f"Events: {result.paths.events_json}")
    print(f"Readable log: {result.paths.readable_log}")
    print(f"Morning digest: {result.paths.digest}")
    return 0


def _format_sensor_line(reading: dict[str, object]) -> str:
    def num(key: str, suffix: str) -> str | None:
        value = reading.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return f"{value:g}{suffix}"

    parts: list[str] = []
    for key, suffix in (
        ("room_temperature_c", " C"),
        ("room_humidity_pct", "% RH"),
        ("room_pressure_hpa", " hPa"),
    ):
        rendered = num(key, suffix)
        if rendered is not None:
            parts.append(rendered)
    gas = reading.get("room_gas_resistance_ohms")
    if isinstance(gas, (int, float)) and not isinstance(gas, bool):
        parts.append(f"{gas / 1000:.0f} kohm gas")
    if "person_present" in reading:
        parts.append("present" if reading["person_present"] else "absent")
    if "motion_detected" in reading:
        parts.append("motion" if reading["motion_detected"] else "still")
    for key, suffix in (
        ("room_illuminance_lx", " lux"),
        ("target_distance_cm", " cm"),
        ("target_count", " target(s)"),
        ("radar_respiratory_rate", "/min breathing"),
        ("radar_heart_rate_bpm", " bpm heart"),
    ):
        rendered = num(key, suffix)
        if rendered is not None:
            parts.append(rendered)
    scene = describe_presence_scene(
        reading.get("person_present"), reading.get("motion_detected")
    )
    if scene is not None:
        parts.append(f"scene: {scene}")
    return " | ".join(parts) if parts else "no readings yet"


def _sensors_live_command(args: argparse.Namespace, config: AppConfig) -> int:
    if args.interval <= 0:
        raise SystemExit("--interval must be positive")
    if args.host:
        config = replace(
            config,
            sensors=replace(
                config.sensors,
                radar=replace(config.sensors.radar, host=args.host),
            ),
        )
    readers = build_sensor_readers(config.sensors)
    if not readers:
        raise SystemExit(
            "No sensors enabled. Set [sensors.air]/[sensors.motion]/[sensors.radar]"
            " enabled = true in the config."
        )

    for reader in readers:  # kick any background connections (e.g. the radar)
        try:
            reader.read()
        except Exception:
            pass

    forever = args.duration <= 0
    print(
        f"Live readout of {len(readers)} sensor reader(s)"
        + (" — Ctrl-C to stop." if forever else f" for {args.duration:g}s.")
    )
    start = time.monotonic()
    end = start + args.duration
    try:
        while forever or time.monotonic() < end:
            merged: dict[str, object] = {}
            for reader in readers:
                try:
                    merged.update(reader.read())
                except Exception:
                    pass
            elapsed = int(time.monotonic() - start)
            print(f"  [{elapsed:>5}s] {_format_sensor_line(merged)}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _read_sensor_snapshot(
    readers: Sequence[object],
    warm_seconds: float = 2.0,
) -> dict[str, object]:
    for reader in readers:  # kick background connections (e.g. the radar)
        try:
            reader.read()
        except Exception:
            pass
    if warm_seconds > 0 and readers:
        time.sleep(warm_seconds)
    snapshot: dict[str, object] = {}
    for reader in readers:
        try:
            snapshot.update(reader.read())
        except Exception:
            pass
    return snapshot


def _transcribe(model: object, audio: object) -> str:
    segments, _ = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        temperature=0.0,
    )
    return " ".join(segment.text for segment in segments).strip()


def _listen_assistant_command(args: argparse.Namespace, config: AppConfig) -> int:
    import queue
    from collections import deque

    import numpy as np

    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover - hardware path
        raise SystemExit("sounddevice is required (pip install '.[mic]').") from exc
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - hardware path
        raise SystemExit(
            "faster-whisper is required (pip install faster-whisper)."
        ) from exc

    # The USB mic may not support 16 kHz natively, so capture at its native rate
    # and resample each closed utterance to 16 kHz for Whisper.
    try:
        native_rate = int(sd.query_devices(args.device, "input")["default_samplerate"])
    except Exception:
        native_rate = 48_000
    target_rate = 16_000
    frame_ms = 30
    frame_samples = max(1, round(native_rate * frame_ms / 1000))
    start_speech_frames = 3
    end_silence_frames = max(1, round(500 / frame_ms))  # ~0.5 s of silence closes it
    max_frames = max(1, round(8000 / frame_ms))  # 8 s hard cap

    print(f"Loading speech-to-text ({args.model_size})...")
    model = WhisperModel(args.model_size, device="cpu", compute_type=args.compute_type)
    readers = build_sensor_readers(config.sensors)
    for reader in readers:  # warm background connections (e.g. the radar)
        try:
            reader.read()
        except Exception:
            pass
    speak_config = replace(config.narrator, voice_enabled=True)
    wake_words = tuple(args.wake_word) if args.wake_word else WAKE_WORDS

    frames_q: queue.Queue = queue.Queue()

    def on_audio(indata, frames, time_info, status) -> None:  # pragma: no cover
        frames_q.put(indata[:, 0].copy())

    pre_roll: deque = deque(maxlen=start_speech_frames + 2)
    buffer: list = []
    in_utterance = False
    speech_run = 0
    silence_run = 0
    deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
    print(
        f'Listening — say "{wake_words[0].title()}, what is the humidity?"'
        " (Ctrl-C to stop)."
    )
    try:
        with sd.InputStream(
            samplerate=native_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            device=args.device,
            callback=on_audio,
        ):
            while deadline is None or time.monotonic() < deadline:
                try:
                    frame = frames_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                pre_roll.append(frame)
                is_speech = float(np.sqrt(np.mean(frame**2))) > args.energy_threshold
                if not in_utterance:
                    if is_speech:
                        speech_run += 1
                        if speech_run >= start_speech_frames:
                            in_utterance = True
                            buffer = list(pre_roll)
                            silence_run = 0
                    else:
                        speech_run = 0
                    continue
                buffer.append(frame)
                if is_speech:
                    silence_run = 0
                else:
                    silence_run += 1
                if silence_run >= end_silence_frames or len(buffer) >= max_frames:
                    audio = np.concatenate(buffer)
                    in_utterance = False
                    speech_run = 0
                    silence_run = 0
                    buffer = []
                    if native_rate != target_rate:
                        count = int(len(audio) * target_rate / native_rate)
                        audio = np.interp(
                            np.linspace(0, len(audio), count, endpoint=False),
                            np.arange(len(audio)),
                            audio,
                        ).astype(np.float32)
                    question = extract_wake_question(
                        _transcribe(model, audio), wake_words
                    )
                    if question is None:
                        continue  # no wake word — ignore silently
                    snapshot = _read_sensor_snapshot(readers, warm_seconds=0.0)
                    answer = answer_question(question, snapshot)
                    print(f'  heard: "{question}"  ->  {answer}')
                    if not args.no_speak:
                        speak(answer, speak_config)
                        # Drop frames captured while we were speaking, so Lullaby
                        # never transcribes its own voice as a new command.
                        try:
                            while True:
                                frames_q.get_nowait()
                        except queue.Empty:
                            pass
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _ask_command(args: argparse.Namespace, config: AppConfig) -> int:
    question = " ".join(args.question).strip()
    if not question:
        raise SystemExit("Ask a question, e.g. lullaby ask what is the humidity")
    snapshot = _read_sensor_snapshot(build_sensor_readers(config.sensors))
    answer = answer_question(question, snapshot)
    print(answer)
    if args.speak:
        speak(answer, replace(config.narrator, voice_enabled=True))
    return 0


def _sounds_live_command(args: argparse.Namespace, config: AppConfig) -> int:
    if args.seconds <= 0:
        raise SystemExit("--seconds must be positive")
    threshold = (
        args.threshold if args.threshold is not None else config.sounds.threshold
    )
    detector = YamNetTFLiteDetector(args.model)
    source = MicrophoneAudioSource(args.seconds, args.device)
    print(f"Listening for {args.seconds:g}s — make sounds near the mic (Ctrl-C to stop).")
    try:
        for window in source.windows():
            scores = detector.classify(window.samples)
            heard = sorted(
                ((cat, score) for cat, score in scores.items() if score >= threshold),
                key=lambda item: -item[1],
            )
            if heard:
                label = ", ".join(f"{cat} {score:.2f}" for cat, score in heard[:3])
            elif scores:
                top_cat, top_score = max(scores.items(), key=lambda item: item[1])
                label = f"(quiet — loudest: {top_cat} {top_score:.2f})"
            else:
                label = "(no sound categories available)"
            print(f"  [{window.offset_seconds:6.1f}s] {label}")
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _radar_vitals_command(args: argparse.Namespace, config: AppConfig) -> int:
    host = args.host or config.sensors.radar.host
    if not host:
        raise SystemExit(
            "Set a radar host via --host or [sensors.radar].host in the config"
        )
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.interval <= 0:
        raise SystemExit("--interval must be positive")

    reader = Mr60RadarReader(
        host,
        config.sensors.radar.port,
        config.sensors.radar.password,
        include_vitals=True,
    )
    print(f"Radar bench readout from {host} ({RADAR_VITALS_DISCLAIMER}).")
    print("Presence, brightness, distance, breathing and heart are raw radar data.")
    print("None of this is a medical or safety signal or a claim about the baby.")
    reader.read()  # start the background connection

    samples: list[dict[str, object]] = []
    start = time.monotonic()
    end = start + args.duration
    while time.monotonic() < end:
        reading = reader.read()
        elapsed = int(time.monotonic() - start)
        print(f"  [{elapsed:>4}s] {format_radar_reading(reading)}")
        if reading:
            samples.append(dict(reading))
        time.sleep(args.interval)

    print()
    summary = summarise_radar_vitals(samples)
    if summary:
        print(summary)
        if args.speak:
            speak(summary, replace(config.narrator, enabled=True, voice_enabled=True))
    else:
        print(
            "No breathing or heart-rate samples were captured "
            f"({RADAR_VITALS_DISCLAIMER})."
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"disclaimer": RADAR_VITALS_DISCLAIMER, "samples": samples},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Samples written: {args.output}")
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
