Fixed only the two review findings.

Changes:
- [episodes.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/episodes.py:190): crying episodes now use `cry_alert_active`; missing/`None` is no-op, `True` opens, `False` closes.
- [cli.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/cli.py:1602): sampler now late-binds a cry-alert probe and injects `cry_alert_active` into a copied tracker snapshot.
- [liveview.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/liveview.py:1509): minimal sink added so CLI can bind the actual `_AlertState`.
- [replay_fixture_night.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/scripts/replay_fixture_night.py:241): replay no longer merges engine snapshots into tracker input.
- [sensor_store.py](/Users/elzekmo/Code/Labie.codex/fix-voice-cry-doctor/src/beddington/sensor_store.py:251): event cry counts now use the same overlap window as legacy rows.

Verification:
- Focused tests passed: `15 passed`
- Replay passed: `PASS episode_kinds`, `PASS final_state`, `PASS states_seen`
- Broad non-socket suite passed with `--ignore=tests/test_liveview.py --ignore=tests/test_worker.py`
- `py_compile` passed for touched liveview files

I did not run any git commands. I did not run the full suite including `tests/test_liveview.py` / `tests/test_worker.py` because this sandbox blocks localhost binds; the rest passed here, and the orchestrator can rerun full outside the sandbox. Edits are intentionally uncommitted.