# Repair pass — fix ONLY these two review findings, nothing else

You previously implemented three bug fixes in this worktree (voice soothe duck-race, crying
persistence, pi_doctor token read). Review found one BLOCKER and one MINOR issue. Fix only these.

## Finding 1 (BLOCKER) — crying episodes can never record in production

Your `_update_crying` keys off `snapshot["baby_state"]`, and the replay script makes that work by
merging the engine snapshot into the readings dict. But in PRODUCTION the tracker is fed raw
sensor readings only: the sampler calls `_read_sensor_snapshot(self._readers, ...)` at
`src/beddington/cli.py:1643` and passes that dict to `_record_episodes` → `tracker.update`
(cli.py:1647, :1601-1610). That dict has keys like `motion_detected` / `person_present` /
`room_temperature_c` — there is NO `baby_state` key. So on the real device `_update_crying`
returns immediately, forever. The replay harness masked this (and its snapshot-merge also makes
replay episode behaviour diverge from production for the other trackers).

Required fix:
- Change `EpisodeTracker._update_crying` to key off a raw boolean key `cry_alert_active`:
  key missing or None → no-op (neither open nor close); True → open `"crying"`; False → close.
- Production wiring: the sampler class in cli.py (the one with the `set_frame_age` late-binding
  pattern, ~cli.py:1596) gets an analogous late-bound probe, e.g. `set_cry_alert_probe(callable)`.
  In `_record_episodes` (or just before `tracker.update`), when the probe is set and returns a
  bool, inject `snapshot["cry_alert_active"] = <bool>` (do not mutate the caller's dict if it is
  reused — copy if needed). Bind it where the live-view server wiring already connects the sampler
  and the alert state: liveview's `_AlertState` has a `.snapshot()` returning a dict with an
  `"active"` bool (used at liveview.py:1143). Follow the exact same wiring path used for
  `set_frame_age` to reach the sampler at serve time. Prefer wiring in cli.py; touch liveview.py
  ONLY if strictly necessary to expose the alert state reference, with the smallest possible
  change.
- Replay script: REVERT the engine-snapshot merge (`tracker_snapshot = dict(readings);
  tracker_snapshot.update(snapshot)`) so the tracker again receives production-shaped input;
  instead inject `cry_alert_active` into the readings dict from the tick's `alert.active` field.
  Fixture expectations (`crying` in episode_kinds/states_seen) must still pass `--check`.
- Tests: update the episode tests to the new key (calm→crying→calm via cry_alert_active
  True/False; missing key mid-cry does not close). If reasonably cheap, add a test that the
  sampler injects `cry_alert_active` from the probe; skip it if the sampler class is too awkward
  to instantiate in a test, and say so.

## Finding 2 (MINOR) — cry count window asymmetry

In `SensorStore.cry_episode_count_since` your new events count uses `started_ts>=?` only, while
the legacy `cry_episodes` count uses the overlap form
`started_ts>=? OR (ended_ts IS NOT NULL AND ended_ts>=?)`. A crying event that started before the
window but ended inside it is counted by the legacy query but missed by yours. Make the events
query use the same overlap form, and extend the sensor_store test with one crying event that
started before `since_ts` and ended after it (must be counted).

## Acceptance
- Full suite: `/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q` — note the sandbox blocks
  localhost socket binds, so tests in tests/test_liveview.py / tests/test_worker.py that bind
  127.0.0.1 will fail with PermissionError HERE; run the rest and report. The orchestrator re-runs
  the full suite outside the sandbox.
- `scripts/replay_fixture_night.py --generate` + `--fixture ... --check` passes with `crying`.

## GUARDS (non-negotiable)
- Fix ONLY the two findings above. No refactoring beyond them. Do NOT run any git command.
- Do not touch files other than: src/beddington/cli.py, src/beddington/episodes.py,
  src/beddington/sensor_store.py, src/beddington/liveview.py (only if strictly necessary),
  scripts/replay_fixture_night.py, tests/.
