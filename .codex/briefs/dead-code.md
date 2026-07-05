# Remove verified dead code (Beddington)

## Goal
Delete dead code that was independently confirmed unused by an earlier audit + a Codex
verification pass. Zero runtime behaviour change. The full test suite must stay green.

## Verified facts (ground truth — do NOT re-derive; but DO stop+report if any is wrong)
- `extract_wake_question` (the production ears function, ears.py:69) operates purely on the
  transcript string and does NOT use `iter_utterances` or the `Utterance` dataclass. Both are
  used ONLY by tests. (Verified by reading ears.py:69-105.)
- The runtime plays committed `.mp3` soothe files (config sound_path point at .mp3;
  assets/soothe/catalog.json describes mp3s). The only generated `.wav` the app uses is
  `assets/soothe/chime.wav` (cli.py `_WAKE_CHIME_PATH`). The 12 other `.wav` generators in
  generate_soothe_assets.py produce orphan files nothing references.
- `NullSensorReader` is used ONLY by tests; `build_sensor_readers` never returns it.
- `_deterministic_answer_question` (assistant.py:941) has zero callers; `answer_question`
  calls `_deterministic_answer_result` directly.
- The 3 pronoun constants in child_profile.py are never read (only `CHILD_NAME` is used).
- `_last_active` (liveview.py) and `SensorStore._path` (sensor_store.py) are assigned and
  never read.

## Files in scope
- scripts/fix_loop.sh, scripts/soothe_loop.sh, scripts/soothe_v2_loop.sh,
  scripts/sound_loop.sh, scripts/voice_v2_loop.sh, scripts/overnight_smart_loop.sh  (DELETE all six)
- scripts/generate_soothe_assets.py  (trim to chime-only)
- src/beddington/ears.py + tests/test_ears.py
- src/beddington/sensors.py + tests/test_sensors.py
- src/beddington/assistant.py
- src/beddington/child_profile.py
- src/beddington/liveview.py
- src/beddington/sensor_store.py

## Tasks (do exactly these; nothing else)
1. DELETE the six loop scripts listed above (whole files).
2. scripts/generate_soothe_assets.py: keep ONLY the chime path. Reduce `main()` to write just
   `chime.wav`; keep `_write_wav`, `_chime`, and the transitive helpers `_chime` actually needs
   (e.g. `_sample_count`/`_fade`/imports it uses). REMOVE the 12 orphan generator functions
   (`_white_noise`, `_uterine_whoosh`, `_heartbeat`, `_soothing_music`, `_pink_noise`, `_rain`,
   `_ocean_waves`, `_forest_breeze`, `_night_sky`, `_music_box_lullaby`, `_shushing`, `_fan_hum`)
   and any helper used ONLY by them. Verify `python scripts/generate_soothe_assets.py` still runs
   and writes a valid chime.wav (but do NOT commit the regenerated chime).
3. ears.py: remove `iter_utterances` (function) AND the `Utterance` dataclass (nothing else uses
   them — you re-verify: grep that `Utterance`/`iter_utterances` appear nowhere in src/ except
   their own defs). Remove the `iter_utterances(...)` bullet from the module docstring and drop
   any import now unused (e.g. `Iterator`, `dataclass`) — but ONLY if truly unused after removal.
   In tests/test_ears.py: remove the two tests `test_iter_utterances_segments_one_sentence` and
   `test_iter_utterances_ignores_silence`, and drop `iter_utterances` from the import line.
4. sensors.py: remove the `NullSensorReader` class. In tests/test_sensors.py: remove its import
   and the single assertion/test that uses it (`NullSensorReader().read() == {}`) — remove the
   whole test function if that assertion is its only body; otherwise just that line + import.
5. assistant.py: remove `_deterministic_answer_question` (the unused wrapper only).
6. child_profile.py: remove the 3 unused pronoun constants (keep `CHILD_NAME` and everything else).
7. liveview.py: remove the write-only `_last_active` assignment (and nothing else near it).
8. sensor_store.py: remove the write-only `self._path = path` assignment (keep `path` usage that
   feeds `_conn`/sqlite connection — only the unused stored attribute goes).

## Constraints
- ZERO runtime behaviour change. No refactors, renames, reformatting, or "improvements" beyond
  the deletions above. Match existing style.
- After each removal, remove ONLY imports/helpers that YOUR deletion made unused. Do not touch
  pre-existing unused code elsewhere.
- Python 3.11-3.14.

## Acceptance
- `.venv/bin/python -m pytest -q` (fallback `python3 -m pytest -q`) is fully GREEN.
- `.venv/bin/python -m py_compile src/beddington/*.py` passes.
- `python scripts/generate_soothe_assets.py` runs and produces a chime.wav (revert/leave the
  file; do not stage it).
- `ruff check src/beddington --select F401,F841` reports no NEW unused imports/locals you left behind.

## Non-goals (do NOT touch)
- src/beddington/cli.py `_build_error` — leave it exactly as is (it is a deliberate hold, not
  part of this cleanup).
- ASSISTANT-EXPANSION-PLAN.md — leave it (it is a backlog, partially implemented).
- scripts/setup_models.sh — keep (it is live).
- Any config, deploy unit, asset file, or catalog.json.
- Any behavioural code path.

## GUARDS (non-negotiable)
- Write ONLY inside this worktree. Do NOT run any git command (no add/commit/branch/push/stash).
- Do NOT edit any file outside "Files in scope".
- If any "dead" symbol turns out to be referenced by production code (not tests), STOP and
  report it — do NOT remove it and do NOT work around it.
- If any acceptance check cannot pass, STOP and report — never paper over a red test.
- Print a concise per-item summary + the pytest result + line counts removed.
