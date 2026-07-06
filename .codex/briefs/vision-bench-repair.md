Fix ONLY these two blocking issues, nothing else. No refactoring beyond them. Do not run git.

1. src/beddington/vision_bench.py `_snapshot_value`: the live /snapshot.json has NO "sensors"
   block. `target_count` lives at snapshot["presence"]["target_count"] (verified in
   live_snapshot.py build(): "presence": {..., "target_count": presence.target_count, ...}).
   Change the fallback lookup from the "sensors" sub-dict to the "presence" sub-dict so the
   collect manifest records the real radar target count. Update/extend the collect test to
   assert target_count is read from the presence block.

2. src/beddington/vision_bench.py `collect_frames`: one transient error from
   client.get_snapshot() / client.get_frame() (WorkerHTTPError, urllib.error.URLError, OSError)
   currently kills the whole overnight collection run. Wrap the per-iteration snapshot+frame
   fetch in a try/except for those exception types: log a warning, count it in a new "errors"
   key in the returned summary, sleep the normal interval, and continue. Keep KeyboardInterrupt
   and programming errors propagating. Add a test with a flaky fake client proving collection
   continues after an error and the summary reports errors.

Acceptance: /Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q tests/test_vision_bench.py
all green (the pre-existing test_worker.py local-server test fails to bind under your sandbox —
ignore it; it passes outside).
