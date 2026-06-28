from __future__ import annotations

from .models import Event, NightReport


def build_digest(report: NightReport) -> str:
    recording_seconds = (report.finished_at - report.started_at).total_seconds()
    episodes = _episodes(report.events, recording_seconds)
    notification_count = sum(event.kind == "notification_sent" for event in report.events)
    soothe_count = sum(event.kind == "soothe_attempted" for event in report.events)
    if not episodes:
        return (
            "Beddington did not detect any sustained crying episodes in this recording. "
            f"It analysed {report.windows_processed} audio windows locally."
        )

    durations = [duration for _, duration in episodes]
    total = sum(durations)
    longest = max(durations)
    first_offset = episodes[0][0]
    episode_word = "episode" if len(episodes) == 1 else "episodes"
    notification_word = (
        "notification" if notification_count == 1 else "notifications"
    )
    soothe_sentence = ""
    if soothe_count:
        soothe_word = "preset" if soothe_count == 1 else "presets"
        soothe_sentence = f"Beddington tried {soothe_count} soothe {soothe_word} before escalation. "
    return (
        f"Beddington detected {len(episodes)} sustained crying {episode_word}. "
        f"The first began {_format_offset(first_offset)} after the recording started. "
        f"Together they lasted about {_format_duration(total)}; "
        f"the longest lasted {_format_duration(longest)}. "
        f"{soothe_sentence}"
        f"Beddington sent {notification_count} {notification_word}. "
        "This is an event summary, not a medical or safety assessment."
    )


def _episodes(events: tuple[Event, ...], fallback_end: float) -> list[tuple[float, float]]:
    episodes: list[tuple[float, float]] = []
    active_start: float | None = None
    for event in events:
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


def _format_offset(seconds: float) -> str:
    whole = max(0, round(seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_duration(seconds: float) -> str:
    rounded = max(0, round(seconds))
    if rounded < 60:
        return f"{rounded} second" + ("" if rounded == 1 else "s")
    minutes, remaining = divmod(rounded, 60)
    if remaining:
        return f"{minutes} min {remaining} sec"
    return f"{minutes} minute" + ("" if minutes == 1 else "s")
