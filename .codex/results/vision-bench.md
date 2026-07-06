Implemented the Phase-1 vision bench harness in the scoped files only.

Changed:
- Added [vision_bench.py](/Users/elzekmo/Code/Labie.codex/vision-bench/src/beddington/vision_bench.py) with collect/analyze/labels/report tooling and lazy `UltralyticsBackend`.
- Added `vision-bench` CLI modes in [cli.py](/Users/elzekmo/Code/Labie.codex/vision-bench/src/beddington/cli.py).
- Added `VisionProbeAnalyzer` and registered `vision_probe` in [worker.py](/Users/elzekmo/Code/Labie.codex/vision-bench/src/beddington/worker.py).
- Added optional `vision = ["ultralytics>=8.3,<9"]` in [pyproject.toml](/Users/elzekmo/Code/Labie.codex/vision-bench/pyproject.toml).
- Added tests in [test_vision_bench.py](/Users/elzekmo/Code/Labie.codex/vision-bench/tests/test_vision_bench.py) and extended [test_worker.py](/Users/elzekmo/Code/Labie.codex/vision-bench/tests/test_worker.py).
- Documented usage in [COMPUTER-WORKER.md](/Users/elzekmo/Code/Labie.codex/vision-bench/docs/COMPUTER-WORKER.md).

Verification stopped per your guard: the focused pytest run hit an environment-level failure in an existing worker HTTP test:

`PermissionError: [Errno 1] Operation not permitted` while binding `127.0.0.1:0` in `tests/test_worker.py::test_pi_client_round_trips_and_raises_on_500`.

Result: `18 passed, 1 failed` for `tests/test_vision_bench.py tests/test_worker.py`. I did not run the full suite after that failure.

No git commands were run. I did not commit anything. Not safe to archive yet: verification is blocked by the local server-bind restriction, and the worktree has uncommitted edits.