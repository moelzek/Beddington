Implemented the scoped dead-code cleanup only.

**Per-Item Summary**
- Deleted the six loop scripts.
- Trimmed [generate_soothe_assets.py](/Users/elzekmo/Code/Labie/.claude/worktrees/dead-code-clean/scripts/generate_soothe_assets.py) to write only `chime.wav`.
- Removed `Utterance` / `iter_utterances` and their two tests.
- Removed `NullSensorReader` and its single test.
- Removed `_deterministic_answer_question`.
- Removed the three child pronoun constants.
- Removed write-only `_last_active` and `SensorStore._path`.
- Post-removal `rg` checks found no remaining scoped dead-symbol references.

**Acceptance**
- `python scripts/generate_soothe_assets.py`: blocked by environment, `python: command not found`.
- `python3 scripts/generate_soothe_assets.py`: passed; wrote valid `assets/soothe/chime.wav` as mono, 16-bit, 16 kHz, 4800 frames.
- `python3 -m pytest -q`: failed to start because `pytest` is not installed: `No module named pytest`.
- `python3 -m py_compile src/beddington/*.py`: passed.
- `ruff check src/beddington --select F401,F841`: blocked by environment, `ruff: command not found`.

**Line Counts Removed**
- Deleted scripts: `696` lines total.
- Python/test trims: `342` lines.
- Total removed: `1,038` lines.

No git commands were run, and nothing was staged or committed. The workspace is not safe to archive yet because full pytest/ruff acceptance could not be completed with the missing local tools.