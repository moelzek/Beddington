from __future__ import annotations

import json
import os
from pathlib import Path

from beddington import autosoothe
from beddington.autosoothe import CryWatcher, read_state, write_state


def test_state_roundtrip(tmp_path: Path) -> None:
    p = str(tmp_path / "a.json")
    assert read_state(p) == {"enabled": False, "preset": ""}
    write_state(True, "white_noise", p)
    assert read_state(p) == {"enabled": True, "preset": "white_noise"}
    write_state(False, "", p)
    assert read_state(p)["enabled"] is False


def test_state_missing_is_disabled(tmp_path: Path) -> None:
    assert read_state(str(tmp_path / "none.json")) == {"enabled": False, "preset": ""}


def test_state_malformed_json_is_disabled(tmp_path: Path) -> None:
    # Non-dict-but-valid JSON must not crash the reader (Codex finding).
    p = tmp_path / "bad.json"
    for body in ("[]", "true", '"x"', "42"):
        p.write_text(body)
        assert read_state(str(p)) == {"enabled": False, "preset": ""}


def test_write_state_fsyncs_and_uses_unique_temp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # BUG K11: the write must fsync before the atomic replace (durability on a
    # power loss) and use a UNIQUE temp file (no shared "{path}.tmp" race).
    path = tmp_path / "autosoothe.json"
    fsynced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(
        autosoothe.os,
        "fsync",
        lambda fd: (fsynced.append(fd), real_fsync(fd))[-1],
    )

    result = write_state(True, "white_noise", str(path))

    # Return value is unchanged.
    assert result == {"enabled": True, "preset": "white_noise"}
    # Content survived and reads back correctly.
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "enabled": True,
        "preset": "white_noise",
    }
    assert read_state(str(path)) == {"enabled": True, "preset": "white_noise"}
    # fsync ran before the replace.
    assert fsynced, "os.fsync was not called before os.replace"
    # No leftover temp files (neither the old fixed ".tmp" nor the unique one).
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [path], f"unexpected leftover temp files: {leftovers}"
    assert not (tmp_path / "autosoothe.json.tmp").exists()


def test_write_state_unique_temp_avoids_fixed_name_collision(
    tmp_path: Path,
) -> None:
    # Two writers to the same target must not share a fixed "{path}.tmp".
    path = tmp_path / "autosoothe.json"
    write_state(True, "rain", str(path))
    write_state(False, "waves", str(path))

    assert read_state(str(path)) == {"enabled": False, "preset": "waves"}
    # Only the final target file remains; no stale ".tmp" siblings.
    assert list(tmp_path.iterdir()) == [path]


class _FakeDetector:
    def __init__(self, score: float) -> None:
        self._score = score

    def score(self, _samples: object) -> float:
        return self._score


class _Result:
    def __init__(self, notify: bool) -> None:
        self.notify = notify


class _FakeTracker:
    """Reports a sustained cry (notify) from the Nth observation onward."""

    def __init__(self, notify_at: int) -> None:
        self._notify_at = notify_at
        self._count = 0

    def observe(self, _offset: float, _score: float) -> _Result:
        self._count += 1
        return _Result(self._count >= self._notify_at)


def test_crywatcher_triggers_then_respects_cooldown() -> None:
    watcher = CryWatcher(_FakeDetector(0.9), _FakeTracker(notify_at=2), cooldown_seconds=10)
    assert watcher.observe(0.0, None) is False  # not yet sustained
    assert watcher.last_score == 0.9
    assert watcher.observe(1.0, None) is True  # sustained -> trigger
    assert watcher.observe(2.0, None) is False  # still crying, but within cooldown
    assert watcher.observe(15.0, None) is True  # cooldown elapsed -> trigger again


def test_crywatcher_quiet_never_triggers() -> None:
    # Tracker that never reports sustained crying.
    watcher = CryWatcher(_FakeDetector(0.0), _FakeTracker(notify_at=999), cooldown_seconds=10)
    assert not any(watcher.observe(float(i), None) for i in range(20))
