# Fix three confirmed bugs: voice soothe duck-race, crying persistence, pi_doctor token false-FAIL

## Goal
Three user-visible bugs, each with a verified root cause. Fix all three with tests, nothing else.
"Done" = all three behaviours corrected, new tests cover each, full suite green.

## Verified facts (ground truth — do not re-derive or second-guess)

### Bug 1 — voice soothe commands always play the default preset (soothing_music)
- The listen-assistant voice loop ducks (stops) dashboard playback BEFORE transcribing the
  command: `_duck_dashboard_soothe` call, `src/beddington/cli.py:1013`, result kept in local
  `ducked_soothe` (dict `{"preset": ..., "context": ...}` or None).
- The soothe executor `_soothe_via_dashboard(cmd, port, config)` (`src/beddington/cli.py:2449`)
  handles `"next"` (~line 2488) and `"play_best"` by fetching live `/soothe.json` state. Because
  playback was already ducked, `state["playing"]` is `""`, so
  `_select_next_soothe_preset(state, config)` cannot exclude the just-playing track and
  `best_preset(outcomes, candidates, min_samples, default)` returns the config default —
  `soothing_music` — every time. Same failure shape for `_select_best_soothe_preset`.
- Field evidence (production DB): during a voice session, 10 consecutive
  `sound_played=soothing_music` events, while dashboard button presses played
  ocean_waves/shushing/lofi_rain correctly.
- The voice-loop call site that must pass the ducked info is `src/beddington/cli.py:1114`
  (`answer = _soothe_via_dashboard(...)`). The other call site (~line 973, auto path) has no
  ducked state and should pass None/omit.

### Bug 2 — crying is never persisted (timeline events or voice cry-count)
- `EpisodeTracker.update` (`src/beddington/episodes.py:122-134`) tracks stirring, presence,
  temperature, sensor availability, camera — there is NO crying episode kind at all, so even when
  the live snapshot state is `"crying"`, nothing is written to the events table.
- The snapshot dict passed to `update` is the /snapshot.json payload; the state key is
  `baby_state` (value `"crying"` while a cry alert is active; the snapshot engine already applies
  dwell + a cry-clear grace, so no extra debounce is needed in the tracker).
- Voice "how many cries" reads `SensorStore.cry_episode_count_since`
  (`src/beddington/sensor_store.py:243`), which counts only the `cry_episodes` table. That table
  is written ONLY by the `analyze`/`listen` cry-monitor pipeline (`_record_cry_episodes`,
  `src/beddington/cli.py:513`, called from `_record_run_soothe_outcomes` at :501). The
  listen-assistant never writes it, and the cry monitor cannot run while the assistant owns the
  mic — so the count is structurally always 0 in the normal setup.
- The two writers can never run at the same time (single mic), so counting BOTH sources without
  dedup is acceptable.
- The replay harness `scripts/replay_fixture_night.py` feeds ticks with an
  `alert: {"active": bool, "score": float|null}` field into the engine — an active alert drives
  the `crying` state — and its built-in fixture currently has NO crying segment and no `crying`
  expectation.

### Bug 3 — pi_doctor false "token file is empty" FAIL
- `scripts/pi_doctor.sh:370`:
  `IFS= read -r liveview_secret <"$TOKEN_FILE" || liveview_secret=""`.
  The token file is written by `_write_live_view_token` (`src/beddington/cli.py:1925`) with
  `handle.write(token)` — NO trailing newline. `read` then exits non-zero (EOF without newline)
  even though it populated the variable, and the `|| liveview_secret=""` clobbers it → false
  FAIL "token file is empty" on a healthy 12-byte token file. Verified on hardware: file contains
  a valid token, doctor reports empty.

## Files in scope
- `src/beddington/cli.py` (thread ducked preset into `_soothe_via_dashboard` + selectors)
- `src/beddington/episodes.py` (crying episode tracking)
- `src/beddington/sensor_store.py` (cry count includes `events` kind='crying')
- `scripts/pi_doctor.sh` (newline-safe token read)
- `scripts/replay_fixture_night.py` (built-in fixture gains a crying segment + expectations)
- `tests/` (new/extended tests: test_cli.py, test_episodes.py, test_sensor_store.py,
  test_replay_fixture.py; new test file allowed if cleaner)

## Required changes

### Fix 1 (duck race)
- Add an optional parameter to `_soothe_via_dashboard` (e.g. `ducked: Mapping[str, str] | None = None`).
- Inside the `"next"` and `"play_best"` branches: when the live state's `playing` is empty and a
  ducked preset exists, treat the ducked preset as the current track — it must be EXCLUDED from
  `next` candidates and treated as "current" for best-preset selection. If the state's `context`
  is empty, fall back to the ducked context.
- Prefer passing an explicit current/playing override into `_select_next_soothe_preset` /
  `_select_best_soothe_preset` over mutating the fetched state dict — pick whichever reads
  cleaner with the existing code, but keep both selectors' existing signatures
  backward-compatible (new keyword arg with default).
- Update the call site at cli.py:1114 to pass `ducked_soothe`. Auto path (~:973) unchanged
  behaviour.

### Fix 2 (crying persistence)
- `episodes.py`: add `_update_crying(ts, snapshot, changes)` wired into `update()`, following the
  `_start`/`_end` pattern used by `_update_stirring`: open kind `"crying"` (detail `""`) when
  `snapshot.get("baby_state") == "crying"`, close it when the state is any other non-crying
  value. Missing/None `baby_state` must not open OR close the episode (sensor gap ≠ cry ended);
  `flush()` already closes open episodes generically.
- `sensor_store.py`: `cry_episode_count_since(since_ts)` returns the sum of (a) existing
  `cry_episodes` count and (b) `SELECT COUNT(*) FROM events WHERE kind='crying' AND
  started_ts >= ?`. Keep the method name and signature. One short comment noting the two writers
  are mutually exclusive (single mic) so no dedup is needed.
- `scripts/replay_fixture_night.py`: extend the BUILT-IN generated fixture with a crying segment
  (a few ticks with `alert: {"active": true, "score": 0.9}` and settled presence, then alert
  clears) and add `"crying"` to the fixture's `expect.episode_kinds` and `expect.states_seen`.
  `--check` on the regenerated fixture must pass.

### Fix 3 (pi_doctor)
- Replace the fragile read at scripts/pi_doctor.sh:370 with a newline-safe read, e.g.
  `liveview_secret=$(<"$TOKEN_FILE")` followed by trimming trailing whitespace/newlines, keeping
  the FAIL only when the trimmed value is genuinely empty. Preserve the script's existing style
  and the subsequent checks untouched.
- Testing this: pi_doctor.sh is hardware-oriented bash; if a minimal pytest can exercise just the
  token-read behaviour cheaply (e.g. subprocess running a small `bash -c` that sources/replicates
  ONLY the fixed read on a tmp file without newline), add it; if that would require restructuring
  the script, skip the test and say so in your final report — do NOT restructure pi_doctor.sh for
  testability.

## Acceptance
- New tests, following the existing test styles in each test file:
  1. `_soothe_via_dashboard` `"next"` with ducked preset X and live state playing="" selects a
     preset != X (stub/monkeypatch `_live_view_json` like existing cli soothe tests do).
  2. Same for `"play_best"`: ducked preset is treated as current/excluded.
  3. `EpisodeTracker`: baby_state calm→crying→calm emits start+end of a `"crying"` episode;
     missing baby_state mid-cry does not close it.
  4. `cry_episode_count_since` counts `events` rows with kind='crying' (and still counts legacy
     `cry_episodes` rows).
  5. Replay fixture: regenerated built-in fixture passes `--check` and expects `"crying"`.
- Full suite green: run `/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q` from the
  worktree root (no network needed; do not install anything).

## Non-goals
- No dashboard HTML/JS changes, no changes to the /alert or /soothe HTTP schemas.
- No changes to soothe learning (`best_preset`), autosoothe, or the barge-in duck/resume flow
  itself — only what the selectors consider "current".
- No config default changes, no [llm] changes, no doc rewrites.
- Do not touch worker.py, liveview.py, live_snapshot.py, night_digest.py.
- Do not "improve" adjacent code, comments, or formatting.

## GUARDS (non-negotiable)
- Write ONLY inside this worktree. Do NOT run any git command (no add/commit/branch/push).
- Do NOT edit files outside "Files in scope".
- If a check can't pass or a fact can't be confirmed, STOP and report — never work around it.
