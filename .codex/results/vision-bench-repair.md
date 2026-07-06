Fixed only the two requested issues.

Changed:
- `collect_frames` now reads `target_count` from `snapshot["presence"]["target_count"]`.
- `collect_frames` now catches `WorkerHTTPError`, `urllib.error.URLError`, and `OSError` per iteration, logs a warning, increments `summary["errors"]`, sleeps the normal interval, and continues.

Updated `tests/test_vision_bench.py` to cover both cases.

Verification:
`/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q tests/test_vision_bench.py`

Result: `8 passed`.

No git commands run. Edited files remain uncommitted in the worktree. Safe to archive only after those worktree edits are handled.