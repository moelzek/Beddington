Implemented the three fixes and focused tests.

Changes:
- Voice soothe now passes ducked preset/context into dashboard soothe selection: [cli.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/cli.py:1118)
- `EpisodeTracker` now persists `baby_state == "crying"` episodes without closing on missing state: [episodes.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/episodes.py:130)
- Cry counts now include tracker `events(kind='crying')` plus legacy `cry_episodes`: [sensor_store.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/sensor_store.py:243)
- `pi_doctor.sh` token read is newline-safe: [pi_doctor.sh](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/scripts/pi_doctor.sh:370)
- Built-in replay fixture now includes a crying segment/expectations: [replay_fixture_night.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/scripts/replay_fixture_night.py:102)

Verification:
- Focused regressions: `7 passed`
- Replay CLI `--check`: passed `episode_kinds`, `final_state`, `states_seen`
- Full suite command was run exactly as requested, but failed because this sandbox forbids localhost socket binding. All 23 failures are `PermissionError: [Errno 1] Operation not permitted` from `tests/test_liveview.py` / `tests/test_worker.py` server-bind tests.

I did not run any git commands. Changes are left in the worktree. Safe to archive: not yet, because strict “full suite green” acceptance needs a rerun in an environment that allows binding `127.0.0.1`.