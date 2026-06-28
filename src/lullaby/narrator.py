from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .config import NarratorConfig
from .context import describe_presence_scene
from .models import Event, NightReport
from .soothe import _playback_command, _player_name

_BANNED_NARRATION_WORDS = (
    "safe",
    "asleep",
    "healthy",
    "fine",
    "breathing",
    "tantrum",
    "heart",
    "respiratory",
    "pulse",
)


def build_narration_prompt(report: NightReport) -> str:
    episodes = _cry_episodes(report)
    soothe_attempts = [
        event for event in report.events if event.kind == "soothe_attempted"
    ]
    notifications = [
        event for event in report.events if event.kind == "notification_sent"
    ]

    facts = [
        f"Crying episode count: {len(episodes)}.",
    ]
    if episodes:
        durations = ", ".join(_format_duration(duration) for _, duration in episodes)
        facts.append(f"Crying episode durations: {durations}.")
        facts.append(
            f"Total crying duration: {_format_duration(sum(duration for _, duration in episodes))}."
        )
    else:
        facts.append("No sustained crying episodes were detected.")

    if soothe_attempts:
        names = ", ".join(
            str(event.details.get("name", "soothe preset"))
            for event in soothe_attempts
        )
        facts.append(f"Soothing played: {names}.")
    else:
        facts.append("Soothing played: none.")

    facts.append(_outcome_fact(report.events, len(notifications)))
    facts.extend(_environment_facts(report.events))
    facts.extend(_sound_facts(report.events))

    fact_lines = "\n".join(f"- {fact}" for fact in facts)
    return (
        "You are Lullaby, a baby-monitor companion giving a parent a brief spoken "
        "morning recap. Write 2 to 3 short, plain British English sentences and then stop.\n"
        "State only the derived facts below. Do not interpret, guess causes, judge, "
        "comfort, or comment on any numbers or scores. Mention the crying, the soothing "
        "and its outcome, any room temperature, humidity, brightness, presence, and "
        "movement count given, and any other sounds heard.\n"
        "Treat the room temperature, humidity, brightness, presence, and movement as "
        "best-guess context only.\n"
        "Do not invent, add, or guess any value. If a temperature, humidity, brightness, "
        "presence, or movement value is not listed below, do not mention it at all. Write "
        "only the recap as plain prose: no preamble, no greeting headers, no lists, no "
        "labels, no field names.\n"
        'Say "crying"; do not say "tantrum". Never say the baby is safe, asleep, healthy, '
        "fine, or breathing. Never mention heart rate, breathing rate, or any vital sign. "
        "Do not give medical advice.\n"
        "No raw audio or video is included here. Do not ask for or mention raw media.\n\n"
        "Derived facts:\n"
        f"{fact_lines}"
    )


def narrate(report: NightReport, config: NarratorConfig, digest_fallback: str) -> str:
    if not config.enabled or config.backend != "ollama":
        return digest_fallback

    payload = {
        "model": config.model,
        "prompt": build_narration_prompt(report),
        "stream": False,
        "options": {
            "num_predict": config.num_predict,
            "temperature": config.temperature,
        },
    }
    endpoint = config.host.rstrip("/") + "/api/generate"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "lullaby/0.1",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        text = str(result.get("response", "")).strip()
    except Exception:
        return digest_fallback

    # Small local models sometimes append a stray, contradictory line after a
    # blank line. The faithful recap is the first paragraph, so keep only that.
    text = text.split("\n\n", 1)[0].strip()
    if not text or _contains_banned_word(text):
        return digest_fallback
    return text


def speak(text: str, config: NarratorConfig) -> dict[str, Any]:
    if not config.voice_enabled:
        return {"spoken": False, "reason": "voice_disabled"}
    if not text.strip():
        return {"spoken": False, "reason": "no_text"}

    with tempfile.TemporaryDirectory(prefix="lullaby-voice-") as directory:
        wav_path = Path(directory) / "narration.wav"
        synthesis = _synthesise(text, config, wav_path)
        if not synthesis["created"]:
            return {"spoken": False, "reason": synthesis["reason"]}

        command = _playback_command(wav_path, play_seconds=0.0)
        if command is None:
            return {"spoken": False, "reason": "no_supported_player"}

        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return {"spoken": False, "reason": "player_failed"}

        return {
            "spoken": True,
            "engine": synthesis["engine"],
            "player": _player_name(command),
        }


def _cry_episodes(report: NightReport) -> list[tuple[float, float]]:
    fallback_end = (report.finished_at - report.started_at).total_seconds()
    episodes: list[tuple[float, float]] = []
    active_start: float | None = None
    for event in report.events:
        if event.kind == "cry_started":
            active_start = event.offset_seconds
        elif event.kind == "cry_ended" and active_start is not None:
            duration = event.duration_seconds
            if duration is None:
                duration = max(0.0, event.offset_seconds - active_start)
            episodes.append((active_start, duration))
            active_start = None
    if active_start is not None:
        episodes.append((active_start, max(0.0, fallback_end - active_start)))
    return episodes


def _outcome_fact(events: tuple[Event, ...], notification_count: int) -> str:
    quiet_confirmed = next(
        (event for event in events if event.kind == "soothe_quiet_confirmed"),
        None,
    )
    if quiet_confirmed is not None:
        checks = int(quiet_confirmed.details.get("quiet_checks", 0))
        return f"Quiet-check outcome: crying no longer detected after {checks} quiet checks."

    if any(event.kind == "soothe_settled" for event in events):
        return "Settle outcome: crying ended before parent notification."

    if any(event.kind == "soothe_unresolved" for event in events):
        return "Settle outcome: recording ended before the soothe preset finished."

    if notification_count:
        word = "notification" if notification_count == 1 else "notifications"
        return f"Parent notification outcome: {notification_count} {word} sent."

    return "Parent notification outcome: no parent notification sent."


def _sound_facts(events: tuple[Event, ...]) -> list[str]:
    counts: dict[str, int] = {}
    for event in events:
        if event.kind != "sound_observed":
            continue
        sound = event.details.get("sound")
        if isinstance(sound, str):
            counts[sound] = counts.get(sound, 0) + 1
    if not counts:
        return []
    parts = [
        f"{sound} {count} time{'' if count == 1 else 's'}"
        for sound, count in sorted(counts.items(), key=lambda item: -item[1])
    ]
    return [f"Other sounds heard: {', '.join(parts)}."]


def _environment_facts(events: tuple[Event, ...]) -> list[str]:
    facts: list[str] = []
    latest_temperature: float | None = None
    latest_humidity: float | None = None
    latest_illuminance: float | None = None
    motion_count = 0
    saw_environment_sample = False
    saw_motion = False
    saw_presence = False
    presence_detected = False
    latest_person_present: object = None
    latest_motion: object = None
    for event in events:
        if event.kind != "environment_sample":
            continue
        saw_environment_sample = True
        temperature = _number(event.details.get("room_temperature_c"))
        humidity = _number(event.details.get("room_humidity_pct"))
        illuminance = _number(event.details.get("room_illuminance_lx"))
        if temperature is not None:
            latest_temperature = temperature
        if humidity is not None:
            latest_humidity = humidity
        if illuminance is not None:
            latest_illuminance = illuminance
        if "motion_detected" in event.details:
            saw_motion = True
            latest_motion = event.details["motion_detected"]
            if event.details["motion_detected"] is True:
                motion_count += 1
        if "person_present" in event.details:
            saw_presence = True
            latest_person_present = event.details["person_present"]
            if event.details["person_present"] is True:
                presence_detected = True
    if latest_temperature is not None:
        facts.append(
            f"Best-guess room temperature context: {_format_measure(latest_temperature)} C."
        )
    if latest_humidity is not None:
        facts.append(
            f"Best-guess room humidity context: {_format_measure(latest_humidity)}%."
        )
    if latest_illuminance is not None:
        facts.append(
            f"Best-guess room brightness context: {_format_measure(latest_illuminance)} lux."
        )
    if saw_environment_sample and saw_motion:
        facts.append(
            f"Movement noticed {motion_count} time{'' if motion_count == 1 else 's'}."
        )
    if saw_presence:
        facts.append(
            "Best-guess presence context: someone was detected in the room."
            if presence_detected
            else "Best-guess presence context: no one was detected in the room."
        )
    scene = describe_presence_scene(latest_person_present, latest_motion)
    if scene is not None:
        facts.append(f"Best-guess scene: {scene}.")
    return facts


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_measure(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _format_duration(seconds: float) -> str:
    rounded = max(0, round(seconds))
    if rounded < 60:
        return f"{rounded} second" + ("" if rounded == 1 else "s")
    minutes, remaining = divmod(rounded, 60)
    if remaining:
        return f"{minutes} min {remaining} sec"
    return f"{minutes} minute" + ("" if minutes == 1 else "s")


def _contains_banned_word(text: str) -> bool:
    return any(
        re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        for word in _BANNED_NARRATION_WORDS
    )


def _synthesise(
    text: str,
    config: NarratorConfig,
    wav_path: Path,
) -> dict[str, Any]:
    if config.voice_engine == "piper":
        result = _synthesise_piper(text, config, wav_path)
        if result["created"]:
            return result
        fallback = _synthesise_espeak(text, wav_path)
        if fallback["created"]:
            return fallback
        return result if result["reason"] != "tts_failed" else fallback
    return _synthesise_espeak(text, wav_path)


def _synthesise_piper(
    text: str,
    config: NarratorConfig,
    wav_path: Path,
) -> dict[str, Any]:
    binary = _resolve_executable(config.piper_binary)
    model = Path(config.piper_model).expanduser()
    if binary is None:
        return {"created": False, "reason": "tts_engine_not_found"}
    if not model.exists():
        return {"created": False, "reason": "piper_model_not_found"}

    try:
        subprocess.run(
            [binary, "--model", str(model), "--output_file", str(wav_path)],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {"created": False, "reason": "tts_failed"}
    if not wav_path.exists():
        return {"created": False, "reason": "tts_failed"}
    return {"created": True, "engine": "piper"}


def _synthesise_espeak(text: str, wav_path: Path) -> dict[str, Any]:
    binary = shutil.which("espeak-ng")
    if binary is None:
        return {"created": False, "reason": "tts_engine_not_found"}
    try:
        subprocess.run(
            [binary, "-v", "en-gb", "-w", str(wav_path), "--stdin"],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {"created": False, "reason": "tts_failed"}
    if not wav_path.exists():
        return {"created": False, "reason": "tts_failed"}
    return {"created": True, "engine": "espeak-ng"}


def _resolve_executable(value: str) -> str | None:
    expanded = Path(value).expanduser()
    if expanded.is_absolute() or "/" in value:
        return str(expanded) if expanded.exists() else None
    return shutil.which(value)
