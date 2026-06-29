# Beddington — soothe for at least 10 minutes after a cry (codex build spec)

You are an autonomous coding agent on **Beddington** (package `beddington` at
`src/beddington/`; tests in `tests/`). Implement **only the unit you are told**,
keep the WHOLE suite green (`pytest -q`), stdlib only, no new dependencies. Never
touch the stale gitignored `src/lullaby/`.

## Problem (observed)
When a sustained cry triggers auto-soothe, the soothe can **stop almost
immediately**:
- With `soothe.quiet_check` OFF (the default), `SootheController.observe()` calls
  `_settle_from()` the moment a `cry_ended` tracker event arrives — so if the baby
  pauses crying after a few seconds, the soothing sound stops within seconds.
- With `quiet_check` ON, it stops as soon as the quiet checks pass (can be < 1 min).

Mo wants the soothing to **keep playing for at least 10 minutes after a cry is
detected**, then stop normally.

## Files
`src/beddington/soothe.py` (`SootheController`), `src/beddington/config.py`
(`SootheConfig` + loader + `_validate`), `config/default.toml`,
`config/pi-product.toml`, and tests `tests/test_soothe.py` / `tests/test_config.py`.

Relevant existing behaviour: `observe()` sets `self._active = True` and plays the
step on `escalation_due`; `_settle_from()` (on `cry_ended` when quiet_check is off)
and the quiet-check `resolved` path both call `self.player.stop_all()` and reset.
The player loops the WAV for the step's `play_seconds` (presets already use 1800s).

### M1 — minimum soothe hold of 10 minutes
1. Add `min_play_seconds: float = 600.0` to `SootheConfig` (config.py), load it in
   `load_config` (mirror the existing soothe scalars), and validate it is `>= 0` in
   `_validate`. Add `min_play_seconds = 600.0` under `[soothe]` in BOTH
   `config/default.toml` and `config/pi-product.toml` (with a short comment).
2. In `SootheController`: record the offset when soothing becomes active (first
   `escalation_due`). Do NOT let soothing stop before `min_play_seconds` have
   elapsed since it became active:
   - The `cry_ended` -> `_settle_from()` early-stop must be suppressed until
     `offset_seconds - start >= min_play_seconds` (keep playing; stay active).
   - The quiet-check `resolved` stop must likewise not fire before the minimum.
   - Once the minimum has elapsed, the normal settle/quiet/notify behaviour resumes
     unchanged.
3. Ensure the sound actually keeps playing for the whole minimum: when soothing,
   the effective per-step play duration must be at least `min_play_seconds` (e.g.
   play for `max(_play_seconds(step), min_play_seconds)`, or re-trigger playback if
   a step's audio would end early). Do NOT change the deterministic cry detection,
   timing, notifications, or alarm path — only how long the soothing SOUND persists.

### Acceptance tests (new; must fail on current code)
- quiet_check OFF: trigger soothe at t=0, deliver a `cry_ended` at t~=30s -> assert
  NO `soothe_settled`/stop before `min_play_seconds`, and that it settles/stops at
  or after `min_play_seconds`.
- quiet_check ON: quiet windows that pass before `min_play_seconds` do NOT resolve;
  resolution happens only at/after the minimum.
- config: `min_play_seconds` loads from TOML, defaults to 600.0, and a negative
  value raises `ValueError`.

## Checklist
1. Only this unit's scope. Stdlib only; no new dependency.
2. `pytest -q` green for the whole suite.
3. No banned words; inferences "(best guess)". Don't touch `src/lullaby/`.
4. Output one line of what changed.
