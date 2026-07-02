from __future__ import annotations

import argparse
import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .audio import (
    MicrophoneAudioSource,
    RealtimeWavFileAudioSource,
    WavFileAudioSource,
    _put_drop_oldest,
)
from .assistant import (
    ConversationMemory,
    answer_history_question,
    answer_question,
    is_history_question,
    is_night_question,
    looks_like_soothe_control,
    match_soothe_command,
)
from .intent import translate_soothe_command
from .config import AppConfig, SootheStepConfig, load_config
from .context import describe_presence_scene
from .detector import YamNetTFLiteDetector, ensure_model
from .ears import WAKE_WORDS, extract_wake_question, normalize_transcript
from .digest import build_digest
from .llm import polish_digest
from .models import Event, NightReport
from .narrator import narrate, speak
from .notifications import LiveViewNotifier, LocalNotifier
from .persona import paddingtonise
from .pipeline import run_pipeline
from .radar_vitals import (
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

_DEFAULT_HISTORY_DB = "~/.local/share/beddington/sensors.db"
_WAKE_CHIME_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "soothe" / "chime.wav"
)
_SOOTHE_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "soothe"
_SOOTHE_AUDIO_SUFFIXES = {
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}
_NIGHT_DIGEST_TREND_NIGHTS = 7
_SOOTHE_SUCCESS_EVENTS = {"soothe_quiet_confirmed", "soothe_settled"}
_SOOTHE_FAILURE_EVENTS = {"soothe_unresolved"}
_LIVE_VIEW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{12,}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beddington",
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
        help='Wake-word voice Q&A: say "Hi Beddington, what is the humidity?"',
    )
    listen_assistant.add_argument("--device")
    listen_assistant.add_argument(
        "--seconds", type=float, default=0.0, help="0 (default) runs until Ctrl-C"
    )
    listen_assistant.add_argument("--model-size", default="tiny.en")
    listen_assistant.add_argument("--compute-type", default="int8")
    listen_assistant.add_argument(
        "--energy-threshold",
        type=float,
        default=None,
        help="Fixed speech threshold; if unset, auto-calibrate to the room noise",
    )
    listen_assistant.add_argument(
        "--wake-word",
        action="append",
        help="Override the wake word(s); repeatable (default: Beddington)",
    )
    listen_assistant.add_argument(
        "--dashboard-port",
        type=int,
        default=8088,
        help="Live-view dashboard port for soothe stop/play commands",
    )
    listen_assistant.add_argument(
        "--no-speak", action="store_true", help="Print answers only, do not speak"
    )
    listen_assistant.add_argument(
        "--debug",
        action="store_true",
        help="Log mic energy and every transcript (for tuning/diagnostics)",
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
    live = subparsers.add_parser(
        "live-view",
        help="Serve a LAN-only live camera view (MJPEG) for a phone browser",
    )
    live.add_argument("--port", type=int, default=8088)
    live.add_argument("--camera-num", type=int, default=0)
    live.add_argument(
        "--night-camera-num",
        type=int,
        default=None,
        help="Second camera used as a long-exposure 'night eye'; enables the "
        "day-eye/night-eye split auto-switched on the day/night light level",
    )
    live.add_argument("--width", type=int, default=640)
    live.add_argument("--height", type=int, default=480)
    live.add_argument("--fps", type=int, default=15)
    live.add_argument(
        "--rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Rotate the displayed video N degrees clockwise (browser-side)",
    )
    live.add_argument(
        "--night",
        action="store_true",
        help="Low-light mode (longer shutter + higher gain; needs some ambient light)",
    )
    live.add_argument("--token", default=None, help="Access token; generated if unset")
    live.add_argument(
        "--bind",
        default="0.0.0.0",
        help="Interface to bind. Default binds the LAN; do not port-forward this.",
    )
    live.add_argument(
        "--no-sensors",
        action="store_true",
        help="Video only; do not overlay the live room readings on the page",
    )
    live.add_argument("--sensor-interval", type=float, default=3.0)
    live.add_argument(
        "--history-db",
        default=_DEFAULT_HISTORY_DB,
        help="SQLite file persisting derived sensor history (graphs survive restarts)",
    )
    live.add_argument(
        "--history-hours",
        type=float,
        default=12.0,
        help="How many hours of history the graphs show",
    )
    live.add_argument(
        "--no-history",
        action="store_true",
        help="Keep only in-memory history (do not persist to disk)",
    )
    night = subparsers.add_parser(
        "night-digest",
        help="Summarise the night from the persisted sensor history (optionally speak it)",
    )
    night.add_argument("--history-db", default=_DEFAULT_HISTORY_DB)
    night.add_argument("--history-hours", type=float, default=12.0)
    night.add_argument(
        "--speak", action="store_true", help="Speak the digest aloud (Piper)"
    )
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, default=Path("output/latest"))
    parser.add_argument("--model", type=Path)
    parser.add_argument(
        "--history-db",
        default=_DEFAULT_HISTORY_DB,
        help="SQLite file persisting derived sensor and soothe history",
    )
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
    if args.command == "live-view":
        return _live_view_command(args, config)
    if args.command == "night-digest":
        return _night_digest_command(args, config)

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

    soothe_outcomes = (
        _load_soothe_outcomes(args.history_db) if config.soothe.enabled else ()
    )
    result = run_pipeline(
        source=source,
        detector=detector,
        notifier=notifier,
        config=config,
        output_dir=args.output,
        started_at=args.started_at,
        use_llm=args.llm,
        soothe_outcomes=soothe_outcomes,
        sensor_readers=build_sensor_readers(config.sensors),
        sound_classifier=detector.classify if config.sounds.enabled else None,
    )
    _record_run_soothe_outcomes(
        result.report.events,
        args.history_db,
        _build_soothe_presets(config),
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
    # claim about Rayan.
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


def _record_run_soothe_outcomes(
    events: Sequence[Event],
    history_db: str,
    presets: Mapping[str, SootheStepConfig] | None = None,
) -> None:
    if not any(
        event.kind in {"cry_started", "cry_ended"}
        or event.kind in _SOOTHE_SUCCESS_EVENTS
        or event.kind in _SOOTHE_FAILURE_EVENTS
        for event in events
    ):
        return
    import os

    from .sensor_store import SensorStore

    store = None
    try:
        store = SensorStore(os.path.expanduser(history_db))
        _record_cry_episodes(events, store)
        _record_soothe_outcomes(events, store, presets)
    except Exception:
        pass
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _record_cry_episodes(events: Sequence[Event], store: object) -> None:
    active_started_ts: float | None = None
    for event in events:
        if event.kind == "cry_started":
            if active_started_ts is not None:
                store.append_cry_episode(active_started_ts)
            active_started_ts = event.occurred_at.timestamp()
            continue
        if event.kind != "cry_ended":
            continue

        ended_ts = event.occurred_at.timestamp()
        duration = event.duration_seconds
        if active_started_ts is not None:
            started_ts = active_started_ts
            active_started_ts = None
        elif duration is not None:
            started_ts = ended_ts - max(0.0, float(duration))
        else:
            started_ts = ended_ts
        store.append_cry_episode(started_ts, ended_ts, duration)

    if active_started_ts is not None:
        store.append_cry_episode(active_started_ts)


def _record_soothe_outcomes(
    events: Sequence[Event],
    store: object,
    presets: Mapping[str, SootheStepConfig] | None = None,
) -> None:
    sound_name: str | None = None
    context = ""
    for event in events:
        if event.kind == "soothe_attempted":
            name = event.details.get("name")
            sound_name = _soothe_outcome_key(name, presets)
            context = _normalise_soothe_context(event.details.get("context", ""))
            continue
        if event.kind == "soothe_switched":
            sound_name = _soothe_outcome_key(event.details.get("to"), presets)
            if "context" in event.details:
                context = _normalise_soothe_context(event.details.get("context", ""))
            continue
        if event.kind in _SOOTHE_SUCCESS_EVENTS or event.kind in _SOOTHE_FAILURE_EVENTS:
            if sound_name:
                store.append_soothe_outcome(
                    event.occurred_at.timestamp(),
                    sound_name,
                    event.kind in _SOOTHE_SUCCESS_EVENTS,
                    context,
                )
            sound_name = None
            context = ""


def _soothe_outcome_key(
    name: object,
    presets: Mapping[str, SootheStepConfig] | None,
) -> str | None:
    if not name:
        return None
    sound_name = str(name)
    if not presets:
        return sound_name
    for key in sorted(presets):
        if presets[key].name == sound_name:
            return key
    if sound_name in presets:
        return sound_name
    return sound_name


def _normalise_soothe_context(value: object) -> str:
    return str(value or "").strip().lower()


def _load_soothe_outcomes(
    history_db: str,
    context: str | None = None,
) -> list[tuple[float, str, bool]]:
    import os

    from .sensor_store import SensorStore

    store = None
    try:
        store = SensorStore(os.path.expanduser(history_db))
        if context:
            return store.outcomes_since_context(0.0, context)
        return store.outcomes_since(0.0)
    except Exception:
        return []
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _summarise_store_night(store: object, window_seconds: float) -> str:
    from .night_digest import summarise_night

    now = time.time()
    return summarise_night(
        store.series(now - window_seconds),
        aggregates=store.night_aggregates(_NIGHT_DIGEST_TREND_NIGHTS, now_ts=now),
    )


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
    line = " | ".join(parts) if parts else "no readings yet"
    return line


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
    # A few passes so a not-ready cycle (the gas-enabled BME688 returns {} on
    # about half its reads) still fills temperature/humidity/pressure.
    for _ in range(5):
        for reader in readers:
            try:
                snapshot.update(reader.read())
            except Exception:
                pass
        time.sleep(0.05)
    return snapshot


def _is_degenerate(text: str) -> bool:
    """True for Whisper's repetition hallucination on noise (e.g. 'No. No. No.'
    repeated), so it can be dropped instead of mistaken for a command."""
    words = normalize_transcript(text).split()
    if len(words) < 6:
        return False
    if len(words) >= 12 and len(set(words)) / len(words) < 0.35:
        return True
    from collections import Counter

    most_common = Counter(words).most_common(1)[0][1]
    return most_common / len(words) > 0.6


def _transcribe(model: object, audio: object) -> str:
    segments, _ = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=False,  # keep all the speech; VAD-trimming garbled marginal audio
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        temperature=0.0,
        # Bias decoding toward the wake word + topics so marginal audio mangles
        # them less ("Beddington"/"Paddington", "temperature" not "up virtual").
        initial_prompt=(
            "Hey Beddington. Hi Paddington. What is the temperature, humidity, "
            "air pressure, brightness, or air quality? How was the night? "
            "Hi Beddington stop. Stop the music. Play rain. Switch sound."
        ),
    )
    text = " ".join(segment.text for segment in segments).strip()
    return "" if _is_degenerate(text) else text


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
    end_silence_frames = max(1, round(350 / frame_ms))  # ~0.35 s closes it
    max_frames = max(1, round(8000 / frame_ms))  # 8 s hard cap

    print(f"Loading speech-to-text ({args.model_size})...")
    model = WhisperModel(args.model_size, device="cpu", compute_type=args.compute_type)
    readers = build_sensor_readers(config.sensors)
    for reader in readers:  # warm background connections (e.g. the radar)
        try:
            reader.read()
        except Exception:
            pass
    # Read-only handle on the persisted history so "how was the night?" can be
    # answered from it (the live-view service is the writer).
    night_store = None
    try:
        import os

        from .sensor_store import SensorStore

        db_path = os.path.expanduser("~/.local/share/beddington/sensors.db")
        if os.path.exists(db_path):
            night_store = SensorStore(db_path)
    except Exception:
        night_store = None
    speak_config = replace(config.narrator, voice_enabled=True)
    wake_words = tuple(args.wake_word) if args.wake_word else WAKE_WORDS
    dashboard_port = int(getattr(args, "dashboard_port", 8088))
    # Alert the parent over the LAN (via the live-view dashboard) on any
    # sustained cry — this is what makes the always-on assistant a real monitor.
    _alert_notifier = LiveViewNotifier(
        port=dashboard_port, token=(_read_live_view_token() or "")
    )

    def _fire_cry_alert(score: float) -> None:
        result = _alert_notifier.notify(
            "Cry detected", f"Sustained crying (cry score {score:.2f})"
        )
        if args.debug:
            print(f"  [debug] cry alert -> {result}", flush=True)

    auto_watcher = _AutoSootheWatcher(
        config, native_rate, frame_ms, debug=args.debug, on_cry=_fire_cry_alert
    )
    soothe_presets = _build_soothe_presets(config)
    conversation_memory = ConversationMemory()
    # Warm the persona model so the first real reply isn't cold-start slow. Off the
    # critical path: a throwaway restyle whose result we discard. Harmless if the
    # model/Ollama is unavailable (paddingtonise just returns the input).
    if speak_config.persona_enabled:
        try:
            paddingtonise("The room is about 20 degrees Celsius, comfortable.", speak_config)
        except Exception:
            pass

    frames_q: queue.Queue = queue.Queue(maxsize=max(20, round(3000 / frame_ms)))

    def on_audio(indata, frames, time_info, status) -> None:  # pragma: no cover
        _put_drop_oldest(frames_q, indata[:, 0].copy())

    def drain_captured_frames() -> None:
        try:
            while True:
                frames_q.get_nowait()
        except queue.Empty:
            pass

    pre_roll: deque = deque(maxlen=start_speech_frames + 2)
    buffer: list = []
    in_utterance = False
    speech_run = 0
    silence_run = 0
    ducked_soothe: dict[str, str] | None = None
    self_audio_floor = 0.0
    soothe_playing = False
    last_soothe_poll = 0.0
    pending_wake_until = 0.0
    pending_wake_soothe: dict[str, str] | None = None
    deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
    try:
        with sd.InputStream(
            samplerate=native_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            device=args.device,
            callback=on_audio,
        ):
            if args.energy_threshold is not None:
                threshold = args.energy_threshold
                adapt = False
                noise_floor = threshold
            else:
                # Seed the noise floor from ~1.5 s of room noise, then keep
                # tracking it live in the loop (below) so the bar follows the room
                # without ever needing a restart.
                levels: list[float] = []
                calib_until = time.monotonic() + 1.5
                while time.monotonic() < calib_until:
                    try:
                        f = frames_q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    levels.append(float(np.sqrt(np.mean(f**2))))
                levels.sort()
                noise_floor = levels[len(levels) // 2] if levels else 0.012
                high_noise = (
                    levels[min(len(levels) - 1, int(len(levels) * 0.9))]
                    if levels
                    else noise_floor
                )
                # Keep the bar above room/speaker bleed, but low enough for short
                # "Hi Beddington" phrases from the Pi mic to open quickly.
                threshold = max(
                    0.024,
                    min(0.055, round(max(noise_floor * 2.0, high_noise * 1.25), 4)),
                )
                adapt = True
            print(
                f"Listening (speech threshold {threshold:.4f}) — say "
                f'"{wake_words[0].title()}, what is the temperature?" (Ctrl-C to stop).'
            )
            frames_seen = 0
            max_rms = 0.0
            last_beat = time.monotonic()
            while deadline is None or time.monotonic() < deadline:
                try:
                    frame = frames_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                now = time.monotonic()
                if pending_wake_until and now >= pending_wake_until:
                    resumed = _resume_dashboard_soothe(
                        pending_wake_soothe,
                        port=dashboard_port,
                    )
                    if args.debug and pending_wake_soothe is not None:
                        print(f"  [debug] wake follow-up timed out; resumed soothe: {resumed}")
                    if pending_wake_soothe is not None:
                        soothe_playing = True
                    pending_wake_until = 0.0
                    pending_wake_soothe = None
                # Reconcile whether a sound is playing (covers dashboard-started
                # music too). Cheap localhost poll, low cadence; keep last value
                # on failure.
                if now - last_soothe_poll >= 2.0:
                    polled = _dashboard_soothe_playing(port=dashboard_port)
                    if polled is not None:
                        soothe_playing = polled
                    last_soothe_poll = now
                pre_roll.append(frame)
                auto_preset = auto_watcher.feed(frame, now)
                if auto_preset:
                    auto_result = _soothe_via_dashboard(
                        {"action": "play", "preset": auto_preset},
                        port=dashboard_port,
                    )
                    soothe_playing = True
                    print(f"  [auto-soothe] sustained crying -> {auto_result}")
                rms = float(np.sqrt(np.mean(frame**2)))
                if adapt and not in_utterance and rms < threshold:
                    # Track the noise floor from quiet frames and keep the bar
                    # just above it (capped, so a close voice always clears it).
                    noise_floor = 0.97 * noise_floor + 0.03 * rms
                    threshold = max(0.024, min(0.055, round(noise_floor * 2.0, 4)))
                # Lift the bar above our own soothe sound so the music we're
                # playing doesn't read as someone talking (see _speech_bar).
                self_audio_floor = _update_self_audio_floor(
                    self_audio_floor,
                    rms,
                    soothe_playing=soothe_playing,
                    in_utterance=in_utterance,
                )
                speech_bar = _speech_bar(
                    threshold, self_audio_floor, soothe_playing=soothe_playing
                )
                is_speech = rms > speech_bar
                if args.debug:
                    frames_seen += 1
                    max_rms = max(max_rms, rms)
                    if time.monotonic() - last_beat >= 5.0:
                        print(
                            f"  [debug] frames={frames_seen} max_rms={max_rms:.4f} "
                            f"(bar {speech_bar:.4f}, self-audio {self_audio_floor:.4f}, "
                            f"soothe={'on' if soothe_playing else 'off'})"
                        )
                        frames_seen = 0
                        max_rms = 0.0
                        last_beat = time.monotonic()
                if not in_utterance:
                    if is_speech:
                        speech_run += 1
                        if speech_run >= start_speech_frames:
                            ducked_soothe = _duck_dashboard_soothe(port=dashboard_port)
                            soothe_playing = False
                            if args.debug and ducked_soothe is not None:
                                print(
                                    "  [debug] paused soothe for voice: "
                                    f"{ducked_soothe['preset']}"
                                )
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
                    pending_resume = ducked_soothe
                    try:
                        audio = np.concatenate(buffer)
                        in_utterance = False
                        speech_run = 0
                        silence_run = 0
                        buffer = []
                        resume_soothe = ducked_soothe
                        ducked_soothe = None
                        if native_rate != target_rate:
                            count = int(len(audio) * target_rate / native_rate)
                            audio = np.interp(
                                np.linspace(0, len(audio), count, endpoint=False),
                                np.arange(len(audio)),
                                audio,
                            ).astype(np.float32)
                        text = _transcribe(model, audio)
                        question = extract_wake_question(text, wake_words)
                        resume_after_answer = resume_soothe
                        now = time.monotonic()
                        from_pending_wake = False
                        if (
                            question is None
                            and pending_wake_until
                            and now < pending_wake_until
                        ):
                            pending_text = normalize_transcript(text)
                            if pending_text:
                                question = pending_text
                                from_pending_wake = True
                                resume_after_answer = resume_after_answer or pending_wake_soothe
                                pending_wake_until = 0.0
                                pending_wake_soothe = None
                                if args.debug:
                                    print(
                                        "  [debug] using wake follow-up as question: "
                                        f"{question!r}"
                                    )
                        if args.debug:
                            print(f'  [debug] transcript="{text}" -> question={question!r}')
                        if question is None:
                            resumed = _resume_dashboard_soothe(
                                resume_soothe,
                                port=dashboard_port,
                            )
                            if resume_soothe is not None:
                                soothe_playing = True
                            if args.debug and resume_soothe is not None:
                                print(f"  [debug] resumed soothe: {resumed}")
                            continue  # no wake word — ignore silently
                        chime = _maybe_play_wake_chime(
                            question,
                            config,
                            already_acknowledged=from_pending_wake,
                        )
                        if args.debug:
                            print(f"  [debug] chime: {chime}")
                        drain_captured_frames()
                        if question == "":
                            pending_wake_until = time.monotonic() + 6.0
                            pending_wake_soothe = resume_after_answer or pending_wake_soothe
                            if args.debug:
                                print("  [debug] wake heard; waiting for follow-up")
                            continue
                        llm_config = _assistant_llm_translator_config(config)
                        soothe_cmd = match_soothe_command(question, soothe_presets)
                        if soothe_cmd is None:
                            llama_soothe_cmd = translate_soothe_command(
                                question,
                                llm_config,
                                soothe_presets,
                            )
                            if llama_soothe_cmd is not None:
                                soothe_cmd = llama_soothe_cmd
                        if soothe_cmd is not None:
                            answer = _soothe_via_dashboard(
                                soothe_cmd,
                                port=dashboard_port,
                                config=config,
                            )
                            _action = str(soothe_cmd.get("action") or "")
                            if _action in {"play", "play_best", "next"}:
                                soothe_playing = True
                            elif _action == "stop":
                                soothe_playing = False
                        elif is_history_question(question):
                            answer = answer_history_question(question, night_store) or (
                                "I don't have enough history yet to answer that."
                            )
                        elif is_night_question(question) and night_store is not None:
                            digest = _summarise_store_night(night_store, 12 * 3600)
                            answer = digest.replace("• ", "").replace("\n", " ")
                        else:
                            snapshot = _read_sensor_snapshot(readers, warm_seconds=0.0)
                            answer = answer_question(
                                question,
                                snapshot,
                                llm_config,
                                memory=conversation_memory,
                            )
                        # Re-voice grounded sensor/action answers as Beddington.
                        # Medically-sensitive vitals are spoken verbatim, and model-led
                        # conversational replies still pass through the same speech path.
                        if soothe_cmd is None:
                            answer = paddingtonise(answer, speak_config)
                        print(f'  heard: "{question}"  ->  {answer}')
                        if not args.no_speak:
                            spoken = speak(answer, speak_config)
                            if args.debug:
                                print(f"  [debug] speak: {spoken}")
                            # Drop frames captured while we were speaking, so Beddington
                            # never transcribes its own voice as a new command.
                            drain_captured_frames()
                        if not _soothe_command_replaces_playback(soothe_cmd):
                            # If the user clearly tried to control playback but we
                            # couldn't parse it into a command, leave the sound
                            # stopped — resuming would bring back the very track
                            # they were trying to stop or change.
                            if (
                                soothe_cmd is None
                                and resume_after_answer is not None
                                and looks_like_soothe_control(question)
                            ):
                                if args.debug:
                                    print(
                                        "  [debug] unrecognised soothe-control; "
                                        "leaving sound stopped"
                                    )
                            else:
                                resumed = _resume_dashboard_soothe(
                                    resume_after_answer,
                                    port=dashboard_port,
                                )
                                if resume_after_answer is not None:
                                    soothe_playing = True
                                if args.debug and resume_after_answer is not None:
                                    print(f"  [debug] resumed soothe: {resumed}")
                    except Exception as exc:  # noqa: BLE001 - one bad utterance must not kill the loop
                        # Isolate a single failed utterance (e.g. a marginal
                        # Whisper decode, a numpy shape error, a transient answer
                        # or speak failure): log it, resume any ducked soothe so we
                        # don't leave the sound paused, reset the capture state, and
                        # keep listening. KeyboardInterrupt is NOT caught here, so
                        # the outer handler still stops the assistant cleanly.
                        if _recover_from_utterance_error(
                            exc,
                            pending_resume,
                            port=dashboard_port,
                            debug=args.debug,
                        ):
                            soothe_playing = True
                        in_utterance = False
                        buffer = []
                        speech_run = 0
                        silence_run = 0
                        ducked_soothe = None
                        continue
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _maybe_play_wake_chime(
    question: str | None,
    config: AppConfig,
    player: Callable[[Path], dict[str, object]] | None = None,
    *,
    already_acknowledged: bool = False,
) -> dict[str, object]:
    if question is None:
        return {"played": False, "reason": "no_wake_word"}
    if already_acknowledged:
        return {"played": False, "reason": "already_acknowledged"}
    if not config.assistant.chime_enabled:
        return {"played": False, "reason": "disabled"}
    play = player or _play_audio_file_once
    return play(_WAKE_CHIME_PATH)


def _play_audio_file_once(path: Path) -> dict[str, object]:
    import subprocess

    from .soothe import _playback_command, _player_name

    if not path.exists():
        return {
            "played": False,
            "reason": "sound_path_not_found",
            "sound_path": str(path),
        }
    command = _playback_command(path, play_seconds=0.0)
    if command is None:
        return {
            "played": False,
            "reason": "no_supported_player",
            "sound_path": str(path),
        }
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {"played": False, "reason": "player_failed", "sound_path": str(path)}
    return {"played": True, "player": _player_name(command), "sound_path": str(path)}


def _ask_command(args: argparse.Namespace, config: AppConfig) -> int:
    question = " ".join(args.question).strip()
    if not question:
        raise SystemExit("Ask a question, e.g. beddington ask what is the humidity")
    snapshot = _read_sensor_snapshot(build_sensor_readers(config.sensors))
    answer = answer_question(question, snapshot, _assistant_llm_translator_config(config))
    print(answer)
    if args.speak:
        speak(answer, replace(config.narrator, voice_enabled=True))
    return 0


def _assistant_llm_translator_config(config: AppConfig) -> object:
    return replace(
        config.narrator,
        enabled=config.assistant.llm_translator.enabled,
    )


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
    print(f"Radar bench readout from {host}.")
    print("Presence, brightness, distance, breathing and heart are raw radar data.")
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
        print("No breathing or heart-rate samples were captured.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"samples": samples},
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


def _lan_ip(fallback: str) -> str:
    """Best-effort local LAN address for the printed URL. Sends no packets — a
    UDP socket 'connect' only resolves the local routing interface."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.0.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return fallback
    finally:
        sock.close()


class _SensorSampler:
    """Owns the sensor readers and refreshes a cached snapshot in the background,
    so the live-view HTTP handler can serve readings without blocking on I/O."""

    def __init__(
        self,
        readers: list,
        interval: float,
        history_seconds: float = 1800,
        store: object | None = None,
        retention_seconds: float = 7 * 24 * 3600,
    ) -> None:
        self._readers = readers
        self._interval = max(0.5, interval)
        self._latest: dict[str, object] = {}
        self._history: deque[tuple[float, dict[str, object]]] = deque(
            maxlen=max(60, int(history_seconds / self._interval))
        )
        self._store = store
        self._retention = retention_seconds
        self._ticks = 0
        self._mode = "day"
        self._override: str | None = None  # "day"/"night" forces; None = auto (lux)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed_store = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        from .liveview import day_night_mode

        while not self._stop.is_set():
            try:
                snapshot = _read_sensor_snapshot(self._readers)
            except Exception:
                snapshot = {}
            if snapshot:
                now = time.time()
                lux = snapshot.get("room_illuminance_lx")
                with self._lock:
                    self._latest = snapshot
                    self._history.append((now, snapshot))
                    if isinstance(lux, (int, float)) and not isinstance(lux, bool):
                        self._mode = day_night_mode(float(lux), self._mode)
                if self._store is not None:
                    try:
                        self._store.append(now, snapshot)
                        # prune old rows roughly once an hour of ticks
                        self._ticks += 1
                        if self._ticks % max(1, int(3600 / self._interval)) == 0:
                            self._store.prune(now - self._retention)
                    except Exception:
                        pass
            self._stop.wait(self._interval)

    def latest(self) -> dict[str, object]:
        with self._lock:
            return dict(self._latest)

    def mode(self) -> str:
        with self._lock:
            return self._override or self._mode

    def override(self) -> str | None:
        with self._lock:
            return self._override

    def set_override(self, value: str | None) -> str:
        """Force day/night, or None to return to auto (light-driven). Returns the
        resulting effective mode."""
        with self._lock:
            self._override = value if value in ("day", "night") else None
            return self._override or self._mode

    def history(self) -> list[tuple[float, dict[str, object]]]:
        with self._lock:
            return list(self._history)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=self._interval + 0.5)
        if self._store is not None and not self._closed_store:
            close = getattr(self._store, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            self._closed_store = True


def _dashboard_fields(snapshot: dict[str, object]) -> dict[str, object]:
    """Build short display strings for the live-view overlay (all sensors),
    reusing the assistant's comfort interpretations for consistency."""
    from .assistant import (
        _air_label,
        _bright_label,
        _humid_label,
        _num,
        _pressure_label,
        _temp_label,
        radar_person_present,
    )

    fields: dict[str, object] = {}
    temp = _num(snapshot, "room_temperature_c")
    if temp is not None:
        fields["temperature"] = f"{temp:.0f}°C · {_temp_label(temp)}"
    humidity = _num(snapshot, "room_humidity_pct")
    if humidity is not None:
        fields["humidity"] = f"{humidity:.0f}% · {_humid_label(humidity)}"
    pressure = _num(snapshot, "room_pressure_hpa")
    if pressure is not None:
        fields["pressure"] = f"pressure {_pressure_label(pressure)}"
    gas = _num(snapshot, "room_gas_resistance_ohms")
    if gas is not None:
        fields["air"] = f"air {_air_label(gas)}"
    lux = _num(snapshot, "room_illuminance_lx")
    if lux is not None:
        fields["light"] = _bright_label(lux)
    # Radar-driven presence (the PIR has been removed): trust the radar's "present"
    # flag only when corroborated by a real target or breathing lock (see
    # radar_person_present), so bare-flag clutter never shows a phantom person.
    if radar_person_present(snapshot):
        fields["presence"] = "● someone present"
    elif snapshot.get("person_present") is not None:
        fields["presence"] = "○ no one detected"
    resp = _num(snapshot, "radar_respiratory_rate")
    heart = _num(snapshot, "radar_heart_rate_bpm")
    # Only surface vitals on a genuine breathing lock. Heart alone (with the
    # implausible breathing already filtered out) is a phantom clutter reading,
    # so it must not show on the always-on dashboard.
    if resp is not None:
        bits = [f"breathing ~{resp:.0f}"]
        if heart is not None:
            bits.append(f"heart ~{heart:.0f}")
        fields["vitals"] = "from radar: " + ", ".join(bits)
    return fields


def _build_soothe_presets(config: AppConfig) -> dict[str, SootheStepConfig]:
    """Soothe presets for the dashboard: configured ones, plus bundled audio."""
    presets: dict[str, SootheStepConfig] = dict(config.soothe.presets)
    catalog = _load_soothe_catalog()
    if _SOOTHE_ASSETS_DIR.is_dir():
        for path in sorted(_SOOTHE_ASSETS_DIR.iterdir()):
            if (
                path.name == "chime.wav"
                or path.suffix.lower() not in _SOOTHE_AUDIO_SUFFIXES
            ):
                continue
            if path.stem not in presets:
                entry = catalog.get(path.stem, {})
                label = str(entry.get("label") or path.stem.replace("_", " "))
                presets[path.stem] = SootheStepConfig(
                    name=label, sound_path=path
                )
    return presets


def _load_soothe_catalog() -> dict[str, dict[str, str]]:
    path = _SOOTHE_ASSETS_DIR / "catalog.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    sounds = raw.get("presets")
    if not isinstance(sounds, dict):
        return {}
    catalog: dict[str, dict[str, str]] = {}
    for key, value in sounds.items():
        if not isinstance(value, dict):
            continue
        catalog[str(key)] = {
            str(field): str(text)
            for field, text in value.items()
            if isinstance(field, str) and isinstance(text, str)
        }
    return catalog


class _DashboardSoothe:
    """Plays a chosen soothe preset on a loop through the Pi speaker, for the
    dashboard's soothe controls. One sound at a time; stop ends it."""

    def __init__(
        self, presets: dict[str, SootheStepConfig], default: str | None = None
    ) -> None:
        from .soothe import SubprocessSoothePlayer

        self._player = SubprocessSoothePlayer()
        self._presets = presets
        self._catalog = _load_soothe_catalog()
        self._default = default if default in presets else next(iter(presets), None)
        self._playing: str | None = None
        self._context = ""
        self._lock = threading.Lock()

    def presets(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for key, step in self._presets.items():
            entry = self._catalog.get(key, {})
            result.append(
                {
                    "key": key,
                    "label": entry.get("label") or step.name or key,
                    "category": entry.get("category", "sounds"),
                    "feel": entry.get("feel", ""),
                    "use": entry.get("use", ""),
                    "avoid": entry.get("avoid", ""),
                }
            )
        return result

    def default(self) -> str | None:
        return self._default

    def autosoothe(self) -> dict[str, object]:
        from .autosoothe import read_state

        return read_state()

    def set_autosoothe(self, enabled: bool, preset: str) -> dict[str, object]:
        from .autosoothe import write_state

        chosen = preset if preset in self._presets else (self._default or "")
        return write_state(enabled, chosen)

    def playing(self) -> str | None:
        with self._lock:
            return self._playing

    def context(self) -> str:
        with self._lock:
            return self._context

    def play(self, name: str, context: str = "") -> dict[str, object]:
        step = self._presets.get(name)
        if step is None:
            return {"ok": False, "playing": self.playing()}
        with self._lock:
            # Loop for hours so it keeps soothing until the parent taps stop.
            loop_step = replace(step, play_seconds=6 * 3600)
            result = self._player.play(loop_step)
            self._playing = name if result.get("played") else None
            self._context = _normalise_soothe_context(context) if self._playing else ""
            return {
                "ok": bool(result.get("played")),
                "playing": self._playing,
                "context": self._context,
                "reason": result.get("reason"),
            }

    def stop(self) -> dict[str, object]:
        with self._lock:
            self._player.stop_all()
            self._playing = None
            self._context = ""
            return {"ok": True, "playing": None, "context": ""}


def _resolve_live_view_token(explicit: str | None) -> str:
    """Return a stable access token. An explicit --token wins; otherwise reuse a
    persisted one (so the phone URL survives restarts/reboots) or create it."""
    if explicit:
        token = explicit.strip()
        if not _LIVE_VIEW_TOKEN_RE.fullmatch(token):
            raise SystemExit("--token must be at least 12 URL-safe characters")
        return token
    import os
    import secrets

    token_path = os.path.expanduser("~/.config/beddington/liveview.token")
    try:
        with open(token_path, encoding="utf-8") as handle:
            existing = handle.read().strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(9)
    try:
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as handle:
            handle.write(token)
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return token


def _read_live_view_token() -> str | None:
    import os

    try:
        with open(
            os.path.expanduser("~/.config/beddington/liveview.token"), encoding="utf-8"
        ) as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def _live_view_json(
    path: str,
    token: str,
    port: int,
    params: Mapping[str, object] | None = None,
    method: str = "GET",
) -> dict[str, object]:
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode({"token": token, **dict(params or {})})
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}?{query}", method=method
    )
    body = urllib.request.urlopen(request, timeout=3).read()
    if not body:
        return {}
    payload = json.loads(body.decode())
    return payload if isinstance(payload, dict) else {}


def _duck_dashboard_soothe(port: int = 8088) -> dict[str, str] | None:
    """Temporarily stop dashboard soothe playback so the wake word can be heard."""
    token = _read_live_view_token()
    if token is None:
        return None
    try:
        state = _live_view_json("/soothe.json", token, port)
    except Exception:
        return None
    preset = str(state.get("playing") or "")
    if not preset:
        return None
    context = _normalise_soothe_context(state.get("context", ""))
    try:
        stopped = _live_view_json(
            "/soothe", token, port, {"action": "stop"}, method="POST"
        )
    except Exception:
        return None
    if stopped.get("ok") is False:
        return None
    return {"preset": preset, "context": context}


def _resume_dashboard_soothe(
    ducked: Mapping[str, str] | None,
    port: int = 8088,
) -> dict[str, object]:
    """Resume a sound paused by ``_duck_dashboard_soothe``."""
    if not ducked:
        return {"ok": True, "playing": None}
    preset = str(ducked.get("preset") or "")
    if not preset:
        return {"ok": True, "playing": None}
    token = _read_live_view_token()
    if token is None:
        return {"ok": False, "reason": "no_token"}
    params: dict[str, object] = {"action": "play", "preset": preset}
    context = _normalise_soothe_context(ducked.get("context", ""))
    if context:
        params["context"] = context
    try:
        return _live_view_json("/soothe", token, port, params, method="POST")
    except Exception:
        return {"ok": False, "reason": "request_failed"}


def _recover_from_utterance_error(
    exc: BaseException,
    ducked_soothe: Mapping[str, str] | None,
    *,
    port: int = 8088,
    debug: bool = False,
    resume: Callable[..., object] | None = None,
) -> bool:
    """Recover the voice loop after a single utterance failed to process.

    One bad Whisper decode (or a transient transcribe/answer/speak error) must
    not kill the whole assistant. This logs the failure and, crucially, resumes
    any soothe that was ducked for the utterance so a mid-utterance crash never
    leaves the sound paused. Returns the new ``soothe_playing`` value (True if a
    ducked sound was resumed). The caller resets the per-utterance capture state
    (in_utterance/buffer/speech_run/silence_run) after calling this.
    """
    resume_fn = resume or _resume_dashboard_soothe
    print(f"  [assistant] skipped an utterance after an error: {exc}", flush=True)
    if debug:
        import traceback

        traceback.print_exc()
    if ducked_soothe is not None:
        resumed = resume_fn(ducked_soothe, port=port)
        if debug:
            print(f"  [debug] resumed soothe after error: {resumed}", flush=True)
        return True
    return False


# --- Self-audio-aware speech gate ------------------------------------------
# When Beddington plays a soothe sound, that sound leaks back into its own mic
# and, to a plain energy detector, looks exactly like a person talking. These
# helpers let the speech bar rise ABOVE the leaked music so (a) the music alone
# never trips a false wake, and (b) only a clearer/closer voice opens a command
# — at which point the loop ducks the music and captures the rest cleanly.
# NOTE: this does not defeat true masking (music louder than the voice at the
# mic is an SNR/hardware limit); it stops the music from fighting the gate.
_SELF_AUDIO_MARGIN = 1.6  # a voice must clear the leaked music by this factor
_SELF_AUDIO_RISE = 0.15  # how fast the floor tracks up toward the music level
_SELF_AUDIO_DECAY = 0.85  # how fast it falls once the music stops / we listen


def _update_self_audio_floor(
    prev: float,
    rms: float,
    *,
    soothe_playing: bool,
    in_utterance: bool,
) -> float:
    """Track the mic energy contributed by our own soothe sound.

    Rises toward the current mic level while a sound is playing and we are not
    mid-utterance; decays once the sound stops or while we are capturing speech
    (the music is ducked then, so the floor should fall).
    """
    if soothe_playing and not in_utterance:
        return (1.0 - _SELF_AUDIO_RISE) * prev + _SELF_AUDIO_RISE * max(0.0, rms)
    return prev * _SELF_AUDIO_DECAY


def _speech_bar(
    base_threshold: float,
    self_audio_floor: float,
    *,
    soothe_playing: bool,
) -> float:
    """The effective 'is this speech?' bar for the current frame.

    With no sound playing this is just the room-noise threshold. While a sound
    plays, the bar is lifted above the leaked-music floor so the music alone
    never registers as speech.
    """
    if not soothe_playing:
        return base_threshold
    return max(base_threshold, round(self_audio_floor * _SELF_AUDIO_MARGIN, 4))


def _dashboard_soothe_playing(port: int = 8088) -> bool | None:
    """Best-effort: is a soothe sound currently playing (dashboard or auto)?

    Returns None on any failure so the caller keeps its last known value.
    """
    token = _read_live_view_token()
    if token is None:
        return None
    try:
        state = _live_view_json("/soothe.json", token, port)
    except Exception:
        return None
    return bool(state.get("playing"))


def _soothe_command_replaces_playback(cmd: Mapping[str, object] | None) -> bool:
    if cmd is None:
        return False
    return str(cmd.get("action") or "") in {"play", "play_best", "next", "stop"}


def _soothe_spoken_name(preset: str) -> str:
    return preset.replace("_", " ")


def _soothe_context_suffix(context: str) -> str:
    return f" for {context}" if context else ""


def _state_preset_metadata(
    state: Mapping[str, object],
    config: AppConfig | None,
) -> dict[str, dict[str, str]]:
    raw_presets = state.get("presets")
    metadata: dict[str, dict[str, str]] = {}
    if isinstance(raw_presets, list):
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if not key:
                continue
            metadata[key] = {
                str(field): str(value)
                for field, value in item.items()
                if isinstance(field, str) and isinstance(value, str)
            }
    if metadata or config is None:
        return metadata

    catalog = _load_soothe_catalog()
    for key, step in _build_soothe_presets(config).items():
        entry = catalog.get(key, {})
        metadata[key] = {
            "key": key,
            "label": entry.get("label") or step.name or key,
            "category": entry.get("category", "sounds"),
            "feel": entry.get("feel", ""),
            "use": entry.get("use", ""),
            "avoid": entry.get("avoid", ""),
        }
    return metadata


def _is_relaxing_candidate(meta: Mapping[str, str]) -> bool:
    text = " ".join(
        meta.get(field, "") for field in ("key", "label", "category", "feel", "use")
    ).lower()
    markers = (
        "gentle", "quiet", "calm", "soothing", "meditation", "wind-down",
        "sleepy", "warm", "slow", "piano", "dream",
    )
    return any(marker in text for marker in markers)


def _candidate_soothe_presets(
    state: Mapping[str, object],
    config: AppConfig | None,
    *,
    category: str = "",
    mood: str = "",
) -> dict[str, object]:
    metadata = _state_preset_metadata(state, config)
    if not metadata:
        return {}

    candidates = dict(metadata)
    if category in {"music", "sounds"}:
        filtered = {
            key: meta
            for key, meta in candidates.items()
            if meta.get("category", "sounds").lower() == category
        }
        if filtered:
            candidates = filtered

    if mood == "relaxing":
        filtered = {
            key: meta
            for key, meta in candidates.items()
            if _is_relaxing_candidate(meta)
        }
        if filtered:
            candidates = filtered
    return candidates


def _preferred_soothe_default(
    candidates: Mapping[str, object],
    state: Mapping[str, object],
    config: AppConfig | None,
    *,
    category: str = "",
    mood: str = "",
    context: str = "",
) -> str:
    preferred: list[str] = []
    if context == "sleep":
        preferred.extend(["dreams", "music_box_lullaby", "soothing_music", "night_sky"])
    elif context == "feeding":
        preferred.extend(["piano", "soothing_music", "river", "pink_noise"])
    if category == "music":
        preferred.extend(["soothing_music", "music_box_lullaby", "dreams", "piano"])
    if mood == "relaxing":
        preferred.extend(["soothing_music", "meditation", "piano", "pink_noise"])
    preferred.append(str(state.get("default") or ""))
    if config is not None:
        preferred.append(config.soothe.preset)
    preferred.extend(sorted(candidates))
    for key in preferred:
        if key in candidates:
            return key
    return next(iter(candidates), "")


def _soothe_min_samples(config: AppConfig | None) -> int:
    learn = getattr(getattr(config, "soothe", None), "learn", None)
    try:
        return max(1, int(getattr(learn, "min_samples", 1)))
    except (TypeError, ValueError):
        return 1


def _soothe_learning_enabled(config: AppConfig | None) -> bool:
    learn = getattr(getattr(config, "soothe", None), "learn", None)
    return bool(getattr(learn, "enabled", False))


def _select_best_soothe_preset(
    state: Mapping[str, object],
    config: AppConfig | None,
    *,
    category: str = "",
    mood: str = "",
    context: str = "",
) -> str | None:
    candidates = _candidate_soothe_presets(
        state, config, category=category, mood=mood
    )
    if not candidates:
        return None
    default = _preferred_soothe_default(
        candidates,
        state,
        config,
        category=category,
        mood=mood,
        context=context,
    )
    if _soothe_learning_enabled(config):
        outcomes = (
            _load_soothe_outcomes(_DEFAULT_HISTORY_DB, context)
            if context
            else _load_soothe_outcomes(_DEFAULT_HISTORY_DB)
        )
    else:
        outcomes = ()
    from .soothe_memory import best_preset

    return best_preset(outcomes, candidates, _soothe_min_samples(config), default)


def _select_next_soothe_preset(
    state: Mapping[str, object],
    config: AppConfig | None,
) -> str | None:
    raw_presets = state.get("presets")
    keys: list[str] = []
    if isinstance(raw_presets, list):
        for item in raw_presets:
            if isinstance(item, dict):
                key = str(item.get("key") or "")
                if key:
                    keys.append(key)
    if not keys and config is not None:
        keys = sorted(_build_soothe_presets(config))
    current = str(state.get("playing") or "")
    candidates = {key: object() for key in keys if key != current}
    if not candidates:
        return None

    config_default = ""
    if config is not None:
        config_default = config.soothe.preset
    default = str(state.get("default") or config_default or "")
    if default not in candidates:
        default = config_default if config_default in candidates else sorted(candidates)[0]

    from .soothe_memory import best_preset

    context = _normalise_soothe_context(state.get("context", ""))
    if _soothe_learning_enabled(config):
        outcomes = (
            _load_soothe_outcomes(_DEFAULT_HISTORY_DB, context)
            if context
            else _load_soothe_outcomes(_DEFAULT_HISTORY_DB)
        )
    else:
        outcomes = ()
    return best_preset(outcomes, candidates, _soothe_min_samples(config), default)


def _autosoothe_preset(config: AppConfig | None, requested: object = None) -> str:
    presets = _build_soothe_presets(config) if config is not None else {}
    value = str(requested or "")
    if value and (not presets or value in presets):
        return value
    try:
        from .autosoothe import read_state

        existing = str(read_state().get("preset") or "")
        if existing and (not presets or existing in presets):
            return existing
    except Exception:
        pass
    if config is not None and (not presets or config.soothe.preset in presets):
        return config.soothe.preset
    return next(iter(presets), "white_noise")


def _write_autosoothe_voice_state(
    enabled: bool,
    config: AppConfig | None,
    requested_preset: object = None,
) -> str:
    from .autosoothe import write_state

    preset = _autosoothe_preset(config, requested_preset)
    try:
        write_state(enabled, preset)
    except OSError:
        return "Sorry, I couldn't update auto-soothe."
    if enabled:
        return "Okay, I'll start watching for crying."
    return "Okay, I'll stop watching for crying."


def _adjust_playback_volume(direction: str) -> dict[str, object]:
    import shutil
    import subprocess

    up = direction == "up"
    commands = []
    if shutil.which("amixer"):
        commands.append(["amixer", "sset", "Master", "5%+" if up else "5%-"])
    if shutil.which("pactl"):
        commands.append(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%" if up else "-5%"])
    if shutil.which("osascript"):
        delta = 8 if up else -8
        bound = "100" if up else "0"
        compare = ">" if up else "<"
        script = (
            "set currentVolume to output volume of (get volume settings)\n"
            f"set newVolume to currentVolume + {delta}\n"
            f"if newVolume {compare} {bound} then set newVolume to {bound}\n"
            "set volume output volume newVolume"
        )
        commands.append(["osascript", "-e", script])
    for command in commands:
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return {"ok": True, "backend": command[0]}
        except (OSError, subprocess.SubprocessError):
            continue
    return {"ok": False, "reason": "unsupported"}


def _record_dashboard_soothe_feedback(
    state: Mapping[str, object],
    success: bool,
    context: str,
) -> str:
    preset = str(state.get("playing") or "")
    if not preset:
        return "I don't have a playing sound to remember right now."
    outcome_context = context or _normalise_soothe_context(state.get("context", ""))
    import os

    from .sensor_store import SensorStore

    store = None
    try:
        store = SensorStore(os.path.expanduser(_DEFAULT_HISTORY_DB))
        store.append_soothe_outcome(time.time(), preset, success, outcome_context)
    except Exception:
        return "Sorry, I couldn't remember that soothe result."
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
    suffix = _soothe_context_suffix(outcome_context)
    if success:
        return f"Noted, I'll remember that {_soothe_spoken_name(preset)} helped{suffix}."
    return f"Noted, I'll try something else next time{suffix}."


def _soothe_via_dashboard(
    cmd: Mapping[str, object],
    port: int = 8088,
    config: AppConfig | None = None,
) -> str:
    """Trigger the live-view soothe player over local HTTP so the voice command
    and the dashboard share ONE player (single source of truth)."""
    action = str(cmd.get("action") or "")
    context = _normalise_soothe_context(cmd.get("context", ""))
    if action == "volume":
        direction = str(cmd.get("dir") or "")
        result = _adjust_playback_volume(direction)
        if result.get("ok"):
            return "Okay, a little louder." if direction == "up" else "Okay, a little quieter."
        return "Sorry, I can't change the speaker volume from here."
    if action == "autosoothe":
        return _write_autosoothe_voice_state(
            cmd.get("enabled") is True,
            config,
            cmd.get("preset"),
        )

    token = _read_live_view_token()
    if token is None:
        return "Sorry, I can't reach the soothe player right now."

    if action == "stop":
        params: dict[str, object] = {"action": "stop"}
        spoken = "Okay, stopping the sound."
    elif action == "feedback":
        try:
            state = _live_view_json("/soothe.json", token, port)
            return _record_dashboard_soothe_feedback(
                state,
                cmd.get("success") is True,
                context,
            )
        except Exception:
            return "Sorry, I couldn't reach the soothe player."
    elif action == "next":
        try:
            state = _live_view_json("/soothe.json", token, port)
            preset = _select_next_soothe_preset(state, config)
            if preset is None:
                return "Sorry, there isn't another soothe sound available."
            params = {"action": "play", "preset": preset}
            state_context = _normalise_soothe_context(state.get("context", ""))
            if state_context:
                params["context"] = state_context
            spoken = f"Playing {_soothe_spoken_name(preset)}{_soothe_context_suffix(state_context)}."
        except Exception:
            return "Sorry, I couldn't reach the soothe player."
    elif action == "play_best":
        try:
            state = _live_view_json("/soothe.json", token, port)
            preset = _select_best_soothe_preset(
                state,
                config,
                category=str(cmd.get("category") or ""),
                mood=str(cmd.get("mood") or ""),
                context=context,
            )
            if preset is None:
                return "Sorry, I don't have a matching soothe sound available."
            params = {"action": "play", "preset": preset}
            if context:
                params["context"] = context
            spoken = f"Playing {_soothe_spoken_name(preset)}{_soothe_context_suffix(context)}."
        except Exception:
            return "Sorry, I couldn't reach the soothe player."
    elif action == "play":
        preset = str(cmd.get("preset") or "white_noise")
        params = {"action": "play", "preset": preset}
        if context:
            params["context"] = context
        spoken = f"Playing {_soothe_spoken_name(preset)}{_soothe_context_suffix(context)}."
    else:
        return "Sorry, I didn't recognise that soothe command."

    try:
        state = _live_view_json("/soothe", token, port, params, method="POST")
        if state.get("ok") is False:
            return "Sorry, I couldn't play that sound."
        return spoken
    except Exception:
        return "Sorry, I couldn't reach the soothe player."


class _AutoSootheWatcher:
    """Watches the assistant's mic for sustained crying and returns the preset to
    auto-play when the shared auto-soothe toggle is on. While off it loads no
    detector and does no work, so the wake-word loop is unaffected."""

    # YAMNet's fixed input window (0.975 s at 16 kHz).
    _WINDOW = 15600

    def __init__(
        self,
        config: AppConfig,
        native_rate: int,
        frame_ms: int = 30,
        debug: bool = False,
        on_cry: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        self._native = native_rate
        self._debug = debug
        # Fired on every sustained-cry trigger (cooldown-gated), regardless of
        # the auto-soothe toggle — this is what actually alerts the parent.
        self._on_cry = on_cry
        self._buf: deque = deque(maxlen=max(1, round(1000 / frame_ms)))  # ~1 s
        self._watcher: object | None = None
        self._building = False
        self._start: float | None = None
        self._last_check = 0.0
        self._last_state = -10.0
        self._last_enabled: bool | None = None
        self._state: dict[str, object] = {"enabled": False, "preset": ""}
        self._build_failures = 0
        self._build_retry_until = 0.0
        self._build_error = ""

    def feed(self, frame: object, now: float) -> str | None:
        from .autosoothe import read_state

        if now - self._last_state >= 2.0:
            self._state = read_state()
            self._last_state = now
            enabled = bool(self._state.get("enabled"))
            if self._debug and enabled != self._last_enabled:
                preset = str(self._state.get("preset") or "")
                print(
                    f"  [debug] auto-soothe state: enabled={enabled} "
                    f"preset={preset or '(none)'}",
                    flush=True,
                )
            self._last_enabled = enabled
        # Detection runs ALWAYS — a monitor must detect a cry to alert on it. The
        # enabled toggle only decides whether we ALSO auto-play a soothe sound.
        # (Phase 2 moves YAMNet to the idle Hailo HAT to take this off the CPU.)
        self._buf.append(frame)
        if now - self._last_check < 1.0 or len(self._buf) < self._buf.maxlen:
            return None
        self._last_check = now
        if self._watcher is None:
            # Build the YAMNet detector off the audio thread so the first enable
            # never blocks the wake-word loop (load is ~1.5 s). Skip until ready.
            self._ensure_building(now)
            return None
        import numpy as np

        audio = np.concatenate(list(self._buf))
        if self._native != 16000:
            count = int(len(audio) * 16000 / self._native)
            audio = np.interp(
                np.linspace(0, len(audio), count, endpoint=False),
                np.arange(len(audio)),
                audio,
            ).astype(np.float32)
        # Trim/pad to YAMNet's fixed window so .score() never raises on length.
        if len(audio) >= self._WINDOW:
            audio = audio[-self._WINDOW :]
        else:
            audio = np.concatenate(
                [np.zeros(self._WINDOW - len(audio), dtype=np.float32), audio]
            )
        trigger = self._watcher.observe(now - (self._start or now), audio)  # type: ignore[attr-defined]
        if self._debug:
            score = float(getattr(self._watcher, "last_score", 0.0))
            threshold = float(getattr(self._config.detection, "threshold", 0.0))
            print(
                f"  [debug] YAMNet cry score={score:.3f} "
                f"threshold={threshold:.3f} trigger={trigger}",
                flush=True,
            )
        if trigger:
            # Always alert (regardless of the soothe toggle).
            if self._on_cry is not None:
                try:
                    self._on_cry(float(getattr(self._watcher, "last_score", 0.0)))
                except Exception:
                    pass
            # Auto-play a soothe sound only when the toggle is on.
            if self._state.get("enabled"):
                return self._preset_to_play()
        return None

    def _preset_to_play(self) -> str | None:
        preset = str(self._state.get("preset") or "")
        learn = getattr(self._config.soothe, "learn", None)
        if not getattr(learn, "enabled", False):
            return preset or None
        try:
            min_samples = int(getattr(learn, "min_samples"))
        except (TypeError, ValueError):
            return preset or None
        if min_samples < 1:
            return preset or None

        import os

        from .sensor_store import SensorStore
        from .soothe_memory import best_preset

        store = None
        try:
            presets = _build_soothe_presets(self._config)
            store = SensorStore(os.path.expanduser(_DEFAULT_HISTORY_DB))
            outcomes = store.outcomes_since(0.0)
            recorded = sum(
                1 for _ts, sound_name, _success in outcomes if sound_name in presets
            )
            if recorded < min_samples:
                return preset or None
            return best_preset(outcomes, presets, min_samples, preset) or None
        except Exception:
            return preset or None
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    def _ensure_building(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._building:
            return
        if now < self._build_retry_until:
            if self._debug:
                wait = max(0.0, self._build_retry_until - now)
                print(
                    "  [debug] YAMNet cry watcher unavailable; "
                    f"retrying in {wait:.0f}s",
                    flush=True,
                )
            return
        self._building = True
        if self._debug:
            print("  [debug] YAMNet cry watcher loading...", flush=True)
        threading.Thread(target=self._do_build, daemon=True).start()

    def _do_build(self) -> None:
        try:
            watcher = self._build()
            self._start = time.monotonic()
            self._watcher = watcher
            self._build_failures = 0
            self._build_retry_until = 0.0
            self._build_error = ""
            if self._debug:
                print("  [debug] YAMNet cry watcher ready", flush=True)
        except Exception as exc:
            self._build_failures += 1
            delay = min(300.0, 30.0 * (2 ** (self._build_failures - 1)))
            self._build_retry_until = time.monotonic() + delay
            self._build_error = str(exc)
            if self._debug:
                print(
                    f"  [debug] YAMNet cry watcher failed: {exc}; "
                    f"retrying in {delay:.0f}s",
                    flush=True,
                )
        finally:
            self._building = False

    def _build(self) -> object:
        from datetime import UTC, datetime

        from .autosoothe import CryWatcher
        from .detector import YamNetTFLiteDetector
        from .state import CryEventTracker

        detector = YamNetTFLiteDetector()
        tracker = CryEventTracker(self._config.detection, datetime.now(UTC))
        return CryWatcher(detector, tracker)


def _night_digest_command(args: argparse.Namespace, config: AppConfig) -> int:
    import os

    from .sensor_store import SensorStore

    store = SensorStore(os.path.expanduser(args.history_db))
    window = max(0.1, args.history_hours) * 3600
    text = _summarise_store_night(store, window)
    store.close()
    print(text)
    if args.speak:
        spoken = text.replace("• ", "").replace("\n", " ")
        speak(spoken, replace(config.narrator, enabled=True, voice_enabled=True))
    return 0


def _live_view_command(args: argparse.Namespace, config: AppConfig) -> int:
    from .liveview import RpicamFrameSource, rpicam_vid_command, serve_live_view

    if args.port <= 0 or args.width <= 0 or args.height <= 0 or args.fps <= 0:
        raise SystemExit("--port, --width, --height and --fps must be positive")

    token = _resolve_live_view_token(args.token)

    # Sensors + providers first, so the night-eye switch can read the day/night mode.
    sampler: _SensorSampler | None = None
    readings_provider = None
    history_provider = None
    digest_provider = None
    if not args.no_sensors:
        import os

        from .liveview import history_series

        readers = build_sensor_readers(config.sensors)
        if readers:
            store = None
            if not args.no_history:
                try:
                    from .sensor_store import SensorStore

                    store = SensorStore(os.path.expanduser(args.history_db))
                except Exception:
                    store = None
            sampler = _SensorSampler(readers, args.sensor_interval, store=store)
            sampler.start()
            readings_provider = lambda: {  # noqa: E731
                **_dashboard_fields(sampler.latest()),
                "mode": sampler.mode(),
                "mode_auto": sampler.override() is None,
            }
            if store is not None:
                window = max(0.1, args.history_hours) * 3600
                history_provider = (  # noqa: E731
                    lambda: store.series(time.time() - window)
                )
                digest_provider = (  # noqa: E731
                    lambda: {"text": _summarise_store_night(store, window)}
                )
            else:
                history_provider = lambda: history_series(sampler.history())  # noqa: E731

    _soothe_presets = _build_soothe_presets(config)
    soothe = (
        _DashboardSoothe(_soothe_presets, config.soothe.preset)
        if _soothe_presets
        else None
    )

    def _make_source(camera: int, night: bool) -> object:
        return RpicamFrameSource(
            rpicam_vid_command(
                camera=camera,
                width=args.width,
                height=args.height,
                fps=args.fps,
                night=night,
            )
        )

    dual = args.night_camera_num is not None
    if dual:
        # Day eye (normal) + night eye (long exposure), shown by the day/night mode.
        sources: dict[str, object] | None = {
            "day": _make_source(args.camera_num, args.night),
            "night": _make_source(args.night_camera_num, True),
        }
        single_source = None
        mode_getter = sampler.mode if sampler is not None else (lambda: "day")
    else:
        sources = None
        single_source = _make_source(args.camera_num, args.night)
        mode_getter = None

    shown_ip = _lan_ip(args.bind if args.bind != "0.0.0.0" else "<pi-ip>")
    url = f"http://{shown_ip}:{args.port}/?token={token}"
    overlay = "video + live room readings" if readings_provider else "video only"

    print("Beddington live view — LAN only, no Internet, no recording, no audio.")
    if dual:
        print(
            f"  Day eye = camera {args.camera_num}, night eye = camera "
            f"{args.night_camera_num} (long exposure), auto-switched on light"
        )
    else:
        mode = " (night / low-light)" if args.night else ""
        print(f"  Camera {args.camera_num}{mode}")
    print(f"  {args.width}x{args.height}, ~{args.fps} fps ({overlay})")
    print(f"  Open on your phone (same WiFi):  {url}")
    print("  The token is required. Keep this on a trusted network; do not")
    print("  port-forward this port. Press Ctrl-C to stop.")
    try:
        serve_live_view(
            host=args.bind,
            port=args.port,
            token=token,
            source=single_source,
            sources=sources,
            mode_getter=mode_getter,
            readings_provider=readings_provider,
            history_provider=history_provider,
            digest_provider=digest_provider,
            soothe=soothe,
            mode_setter=(sampler.set_override if sampler is not None else None),
            rotate=args.rotate,
        )
    except KeyboardInterrupt:
        print("\nLive view stopped.")
    finally:
        if sampler is not None:
            sampler.stop()
        if soothe is not None:
            soothe.stop()
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
