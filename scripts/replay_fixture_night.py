#!/usr/bin/env python3
"""Replay a deterministic synthetic night through Beddington's live logic.

Fixture JSON schema:

```json
{
  "name": "synthetic-night-1",
  "start_ts": 1700000000.0,
  "ticks": [
    {
      "t": 0.0,
      "readings": {
        "motion_detected": false,
        "person_present": true,
        "target_count": 1,
        "room_temperature_c": 21.0
      },
      "camera_frame_age_s": 0.5,
      "alert": {"active": false, "score": null}
    }
  ],
  "expect": {
    "episode_kinds": [
      "stirring",
      "caregiver_present",
      "room_warm",
      "sensor_unavailable"
    ],
    "final_state": "calm",
    "states_seen": ["calm", "wiggling", "caregiver_present"]
  }
}
```

``t`` is seconds offset from ``start_ts``; absolute timestamp is
``start_ts + t``. Baseline ticks MUST carry ``person_present: true`` plus a
corroborator (``target_count: 1``) so the engine can reach ``calm`` and
``wiggling``. The caregiver-visit section raises ``target_count`` to 2. Only a
truly-empty-room fixture should expect ``not_detected``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from beddington.config import load_config
from beddington.episodes import EpisodeChange, EpisodeTracker
from beddington.live_snapshot import History, LiveSnapshotEngine

Tick = dict[str, Any]
Fixture = dict[str, Any]


def _baseline(
    *,
    motion: bool = False,
    target_count: int = 1,
    temperature_c: float = 21.0,
) -> dict[str, object]:
    return {
        "motion_detected": motion,
        "person_present": True,
        "target_count": target_count,
        "target_distance_cm": 95.0,
        "room_temperature_c": temperature_c,
    }


def _tick(
    t: float,
    readings: dict[str, object],
    alert: dict[str, object] | None = None,
) -> Tick:
    return {
        "t": float(t),
        "readings": readings,
        "camera_frame_age_s": 0.5,
        "alert": alert or {"active": False, "score": None, "age_seconds": None},
    }


def built_in_fixture() -> Fixture:
    """Return the deterministic built-in night fixture."""
    ticks: list[Tick] = []
    for offset in range(0, 7201, 10):
        readings: dict[str, object]
        if 1200 <= offset <= 1250:
            readings = _baseline(motion=True)
        elif 1800 <= offset <= 1910:
            readings = _baseline(target_count=2)
        elif 2400 <= offset <= 2730:
            readings = _baseline(temperature_c=24.5)
        elif 3000 <= offset <= 3090:
            readings = {}
        elif 3600 <= offset <= 3630:
            readings = _baseline()
            ticks.append(
                _tick(
                    float(offset),
                    readings,
                    {
                        "active": True,
                        "score": 0.9,
                        "age_seconds": float(offset - 3600),
                    },
                )
            )
            continue
        elif offset == 6200:
            readings = _baseline(motion=True)
        else:
            readings = _baseline()
        ticks.append(_tick(float(offset), readings))

    return {
        "name": "synthetic-night-1",
        "start_ts": 1700000000.0,
        "ticks": ticks,
        "expect": {
            "episode_kinds": [
                "stirring",
                "caregiver_present",
                "room_warm",
                "sensor_unavailable",
                "crying",
            ],
            "final_state": "calm",
            "states_seen": ["calm", "wiggling", "caregiver_present", "crying"],
        },
    }


def generate_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, built_in_fixture())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_fixture(path: Path) -> Fixture:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("fixture root must be an object")
    return data


def _float(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _alert(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {"active": False, "score": None, "age_seconds": None}
    return {
        "active": raw.get("active") is True,
        "score": raw.get("score"),
        "age_seconds": raw.get("age_seconds"),
        "title": raw.get("title", ""),
        "message": raw.get("message", ""),
        "seq": raw.get("seq", 0),
    }


def _episode(change: EpisodeChange) -> dict[str, object]:
    return {
        "action": change.action,
        "kind": change.kind,
        "ts": change.ts,
        "detail": change.detail,
    }


def _transition(ts: float, start_ts: float, snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "ts": ts,
        "t": round(ts - start_ts, 3),
        "state": str(snapshot.get("baby_state", "")),
        "label": str(snapshot.get("label", "")),
    }


def run_replay(fixture: Fixture, config_path: Path) -> tuple[dict[str, object], set[str]]:
    config = load_config(config_path)
    start_ts = _float(fixture.get("start_ts"))
    engine = LiveSnapshotEngine(config.liveview.state, process_start_ts=start_ts)
    tracker = EpisodeTracker()
    history: History = []
    transitions: list[dict[str, object]] = []
    episodes: list[dict[str, object]] = []
    t2_alerts: list[dict[str, object]] = []
    seen_t2: set[tuple[str, int]] = set()
    states_seen: set[str] = set()
    previous_state: str | None = None
    last_ts = start_ts

    raw_ticks = fixture.get("ticks", [])
    if not isinstance(raw_ticks, list):
        raise ValueError("fixture ticks must be a list")

    for raw_tick in raw_ticks:
        if not isinstance(raw_tick, dict):
            raise ValueError("each fixture tick must be an object")
        ts = start_ts + _float(raw_tick.get("t"))
        last_ts = ts
        raw_readings = raw_tick.get("readings", {})
        if not isinstance(raw_readings, dict):
            raise ValueError("tick readings must be an object")
        readings = dict(raw_readings)
        raw_alert = raw_tick.get("alert")
        alert = _alert(raw_alert)
        camera_frame_age_s = raw_tick.get("camera_frame_age_s")
        if not isinstance(camera_frame_age_s, (int, float)) or isinstance(camera_frame_age_s, bool):
            camera_frame_age_s = None

        if readings:
            history.append((ts, readings))

        snapshot = engine.build(
            history=history,
            now=ts,
            alerts=alert,
            mode="night",
            mode_auto=False,
            camera_frame_age_s=camera_frame_age_s,
            soothe_playing=None,
            autosoothe={"enabled": False, "preset": ""},
        )
        tracker_snapshot = dict(readings)
        active = raw_alert.get("active") if isinstance(raw_alert, dict) else None
        if isinstance(active, bool):
            tracker_snapshot["cry_alert_active"] = active
        for change in tracker.update(ts, tracker_snapshot, camera_frame_age_s):
            episodes.append(_episode(change))
        state = str(snapshot.get("baby_state", ""))
        states_seen.add(state)
        if state != previous_state:
            transitions.append(_transition(ts, start_ts, snapshot))
            previous_state = state

        for alert in snapshot.get("alerts", []):
            if not isinstance(alert, dict) or alert.get("tier") != "T2":
                continue
            alert_type = str(alert.get("type", ""))
            seq = int(alert.get("seq", 0) or 0)
            key = (alert_type, seq)
            if key in seen_t2:
                continue
            seen_t2.add(key)
            t2_alerts.append({"ts": ts, "t": round(ts - start_ts, 3), **alert})

    for change in tracker.flush(last_ts):
        episodes.append(_episode(change))

    return (
        {
            "fixture": str(fixture.get("name", "")),
            "transitions": transitions,
            "episodes": episodes,
            "t2_alerts": t2_alerts,
        },
        states_seen,
    )


def _summary(events: dict[str, object]) -> str:
    rows: list[tuple[float, str]] = []
    for transition in events.get("transitions", []):
        if not isinstance(transition, dict):
            continue
        ts = _float(transition.get("ts"))
        rows.append(
            (
                ts,
                f"{ts:.1f} state {transition.get('state')}: {transition.get('label')}",
            )
        )
    for episode in events.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        ts = _float(episode.get("ts"))
        detail = str(episode.get("detail") or "")
        suffix = f" ({detail})" if detail else ""
        rows.append(
            (
                ts,
                f"{ts:.1f} episode {episode.get('action')} {episode.get('kind')}{suffix}",
            )
        )
    return "\n".join(text for _ts, text in sorted(rows, key=lambda item: (item[0], item[1]))) + "\n"


def _check(events: dict[str, object], states_seen: set[str], fixture: Fixture) -> bool:
    expect = fixture.get("expect", {})
    if not isinstance(expect, dict):
        print("SKIP expectations: fixture has no expect object")
        return True

    ok = True
    episodes = {
        str(item.get("kind"))
        for item in events.get("episodes", [])
        if isinstance(item, dict)
    }
    transitions = [
        item for item in events.get("transitions", []) if isinstance(item, dict)
    ]
    final_state = str(transitions[-1].get("state")) if transitions else ""

    expected_episodes = set(expect.get("episode_kinds", []))
    missing_episodes = sorted(expected_episodes - episodes)
    if missing_episodes:
        print(f"FAIL episode_kinds: missing {', '.join(missing_episodes)}")
        ok = False
    else:
        print("PASS episode_kinds")

    expected_final = expect.get("final_state")
    if expected_final is not None and final_state != expected_final:
        print(f"FAIL final_state: expected {expected_final}, got {final_state}")
        ok = False
    else:
        print("PASS final_state")

    expected_states = set(expect.get("states_seen", []))
    missing_states = sorted(expected_states - states_seen)
    if missing_states:
        print(f"FAIL states_seen: missing {', '.join(missing_states)}")
        ok = False
    else:
        print("PASS states_seen")

    return ok


def replay_fixture(
    fixture_path: Path,
    config_path: Path,
    output_dir: Path,
    *,
    check: bool = False,
) -> int:
    fixture = _load_fixture(fixture_path)
    events, states_seen = run_replay(fixture, config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "replay-events.json", events)
    (output_dir / "replay-summary.txt").write_text(_summary(events), encoding="utf-8")
    if check and not _check(events, states_seen, fixture):
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or replay a deterministic Beddington night fixture.",
    )
    parser.add_argument("--generate", type=Path, help="write the built-in fixture")
    parser.add_argument("--fixture", type=Path, help="fixture JSON to replay")
    parser.add_argument("--config", type=Path, help="Beddington TOML config")
    parser.add_argument("--output", type=Path, help="directory for replay output")
    parser.add_argument("--check", action="store_true", help="check fixture expectations")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.generate and (args.fixture or args.config or args.output or args.check):
        parser.error("--generate cannot be combined with replay flags")
    if args.generate:
        generate_fixture(args.generate)
        return 0
    if not args.fixture:
        parser.error("expected --generate PATH or --fixture PATH")
    if args.config is None or args.output is None:
        parser.error("--fixture requires --config CONFIG and --output DIR")
    return replay_fixture(args.fixture, args.config, args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
