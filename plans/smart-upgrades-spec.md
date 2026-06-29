# Lullaby/Beddington smart-upgrades — codex build spec

You are an autonomous coding agent working on **Beddington** (formerly "Lullaby"), a privacy-first baby-monitor companion (Python). You are invoked one **unit** at a time by a driver script. Read this whole file, then implement **only the single unit you are told to**. Keep the entire test suite green.

## Package layout (READ THIS FIRST)

- The live Python package is **`beddington`**, at **`src/beddington/`**. Tests import `from beddington...`. The CLI entry point is `beddington` (e.g. `beddington --help`, `beddington ask "..."`).
- There is a **stale, untracked `src/lullaby/`** directory left over from a rename. **Never read, edit, or create files there.** It is gitignored and dead. All work happens in `src/beddington/`.

## How to run tests (authoritative)

```
pytest -q
```

Tests live in `tests/`, config in `pyproject.toml` (`pythonpath = ["src"]`, `addopts = "-q"`, package `beddington-monitor`, `packages = ["src/beddington"]`). Baseline is **207 passing tests**. Every unit must end with the **whole** suite passing. There is no CI and no lint/typecheck to satisfy — just pytest.

## Hard constraints (never violate)

- **Standard library only.** No new dependencies. Allowed: `sqlite3`, `threading`, `dataclasses`, `tomllib`, `pathlib`, `json`, `datetime`, `urllib`. Do not add anything to `pyproject.toml`.
- **No new ML models.** Target hardware is a Raspberry Pi with ~1.9 GB free RAM. The new "smart" behaviour is plain bookkeeping (counts) and reuse of the *already-configured* local Llama — never a new model or heavy library.
- **Deterministic core stays deterministic.** Do not change cry detection, timing, the cry-event state machine, or the existing branches of the `answer_question` switchboard. New intelligence is additive and, for anything LLM-based, **optional and off by default with a hard fallback**.
- **Privacy.** Raw audio/video never leaves the device. Only derived counts/text are stored. Never log raw audio.
- **No medical/safety claims.** Never emit the banned words (see Safety). Any inference is labelled `(best guess)`.
- **Surgical changes.** Touch only what the current unit needs. Match the surrounding code's style, naming, and test conventions exactly.
- **Tests.** Add or extend tests for every behaviour you introduce, mirroring existing test style (`tmp_path`, `monkeypatch`, `Fake*` doubles).

## Safety — banned words in any user-facing/digest text

Never produce: `asleep, sleeping, slept, safe, healthy, fine, normal, well, breathing` (as a vital sign), or any SIDS/apnoea/fever wording. The night-digest test enforces this; new digest lines must pass it. Label inferences `(best guess)`. Never claim causation ("the sound calmed her") — state the observation ("when <sound> played, she quieted k/n times (best guess)").

## Codebase map & patterns to mirror (all under src/beddington/)

- `src/beddington/sensor_store.py` — on-device SQLite. Connection/schema idiom in `SensorStore.__init__` (`sqlite3.connect(..., check_same_thread=False)`, `PRAGMA journal_mode=WAL`, `CREATE TABLE IF NOT EXISTS`, a `threading.Lock`). `append()`, `series()`, `prune()` show the insert/query/delete style. Mirror this exactly for any new table/method.
- `src/beddington/soothe.py` — `SootheController`. Emits events: `soothe_attempted` (in `_attempt_due_steps`, includes `details["name"]` = preset and `details["sound_path"]`), `soothe_quiet_confirmed` and `soothe_settled` (baby went quiet = **success**), `soothe_unresolved` (escalated = **failure**). These are the outcome signals.
- `src/beddington/autosoothe.py` — `read_state()`/`write_state()` return `{"enabled": bool, "preset": str}` (atomic JSON). `CryWatcher.observe()` returns True when sustained crying should trigger a soothe.
- `src/beddington/cli.py` — `_AutoSootheWatcher.feed()` reads `read_state()` then returns the preset name to play; the run loop calls `_soothe_via_dashboard({"action":"play","preset":...})`. `_build_soothe_presets(config)` lists available presets (config + `assets/soothe/*.wav`). The sensor DB path is under `~/.local/share/`.
- `src/beddington/config.py` — frozen dataclasses (`SootheConfig`, `QuietCheckConfig`, `SootheStepConfig`, `NarratorConfig`, `LlmConfig`). `load_config()` reads TOML; nested loaders like `_load_quiet_check()` show the "read dict → build dataclass with defaults" pattern; `_validate()` raises `ValueError` on bad values. TOML lives in `config/default.toml` and `config/tier1-demo.toml`.
- `src/beddington/night_digest.py` — `summarise_night(series, time_label=None)` builds plain-English `•` bullet lines and returns them joined. New lines slot in here.
- `src/beddington/narrator.py` — `narrate(report, config, digest_fallback)` shows the local-LLM call pattern: POST JSON to `config.host + "/api/generate"` with `{"model": ..., "prompt": ...}` via `urllib.request`, and **degrade to the fallback** on any error / when `config.enabled` is False / backend != "ollama". Reuse this HTTP + graceful-fallback pattern for the translator; do not add an HTTP library.
- `src/beddington/assistant.py` — `answer_question(question, snapshot)` is the deterministic keyword switchboard; it returns `_FALLBACK` when nothing matches. `normalize_transcript`, `_mentions` are the matching helpers.
- Test patterns: `tests/test_sensor_store.py` (SQLite roundtrip), `tests/test_autosoothe.py` (state roundtrip), `tests/test_config.py` (write TOML → `load_config` → assert; `pytest.raises(ValueError, match=...)`), `tests/test_soothe.py` (`Fake*`, `monkeypatch`), `tests/test_narrator.py` (fake LLM via `monkeypatch`).

## Units (implement ONLY the one you are told)

### U1 — soothe outcomes table
In `src/beddington/sensor_store.py` add a `soothe_outcomes(ts REAL, sound_name TEXT, success INTEGER)` table (created in `__init__` with `CREATE TABLE IF NOT EXISTS`, mirror the existing pragma/lock idiom), plus `append_soothe_outcome(timestamp, sound_name, success)` and `outcomes_since(since_ts) -> list[tuple[float,str,bool]]`. Extend `tests/test_sensor_store.py`. Acceptance: roundtrip test stores and reads outcomes; existing tests still pass.

### U2 — best-preset logic (pure)
New `src/beddington/soothe_memory.py` with a pure function `best_preset(outcomes, presets, min_samples, default)`: `outcomes` is the list from `outcomes_since`; pick the preset (restricted to keys in `presets`) with the highest success rate; if any eligible preset has fewer than `min_samples` attempts, prefer the **least-tried** one (exploration); if there is not enough data at all, return `default`. Deterministic (stable tie-break by name). New `tests/test_soothe_memory.py`. No I/O in this module.

### U3 — record outcomes during a run
When a soothe episode resolves, record it via U1: `soothe_quiet_confirmed`/`soothe_settled` → success True; `soothe_unresolved` → success False; `sound_name` from the triggering preset / `soothe_attempted` `details["name"]`. Wire this where soothe events are processed in the run loop (`src/beddington/cli.py`, near where auto-soothe and the store are available). Do not change event emission in `soothe.py`. Add tests proving an episode writes one outcome row with the right success flag.

### U4 — use the memory to pick the sound
In `src/beddington/cli.py` `_AutoSootheWatcher.feed()`, when `config.soothe.learn.enabled` is true and there are at least `min_samples` recorded attempts, choose the preset via `soothe_memory.best_preset(...)` (over `_build_soothe_presets` keys) instead of the configured `read_state()` preset; otherwise keep today's behaviour exactly. Add tests for both branches (learning on with data → best; off or sparse → configured).

### U5 — config for learning
Add a nested `learn` config to `SootheConfig`: `[soothe.learn] enabled (bool, default false)`, `min_samples (int, default 10)`. Add a `_load_soothe_learn()` loader mirroring `_load_quiet_check`, wire it into `load_config`, default it in `config/default.toml` and `config/tier1-demo.toml`, and validate `min_samples >= 1` in `_validate`. Extend `tests/test_config.py`.

### U6 — cross-night aggregates
Add a `SensorStore` query that returns, over the last N nights, (a) the typical times the baby stirs (from cry-related readings/events already stored) and (b) per-sound success tallies (reuse the U1 table). Keep it a simple deterministic aggregate (bucket by hour). Add tests with seeded rows.

### U7 — night-digest trend lines
In `src/beddington/night_digest.py` `summarise_night`, add up to two `•` lines: "Usually stirs around ~Xam (best guess)." and "When <sound> played, she quieted k/n times (best guess)." Only emit when there is enough data; never emit a banned word; always carry `(best guess)`. Extend `tests/test_night_digest.py` (assert the lines appear with seeded data and that the banned-word guard still passes).

### U8 — llama intent translator (pure-ish, fallback-safe)
New `src/beddington/intent.py` with `translate_intent(question, config, ask_llm=None) -> str | None`: when enabled, ask the local LLM (reuse narrator's `urllib`/`/api/generate` pattern; `ask_llm` injectable for tests) to pick exactly one keyword from a fixed allow-list of existing intents; return that keyword or None. On any error / disabled / unavailable → return None. **It never returns a value, only an intent keyword.** New `tests/test_intent.py` using a fake `ask_llm` via injection/`monkeypatch`.

### U9 — wire the translator into answers
In `src/beddington/assistant.py` (or the `ask`/`listen-assistant` path in `cli.py`), when `answer_question` would return `_FALLBACK` and `assistant.llm_translator.enabled` is true, call `translate_intent`; if it returns a known keyword, re-run the deterministic answer for that intent and return that. The **value always comes from the deterministic brain**. Disabled/unavailable → behaviour identical to today. Add `[assistant.llm_translator] enabled` (default false) to config + TOML + validation. Add tests: disabled → unchanged; enabled + fake translator maps "should I crack a window?" → an existing room answer; LLM never fabricates a number.

## Per-unit checklist (every unit)

1. Implement only this unit's scope, only under `src/beddington/`, `tests/`, `config/`.
2. `pytest -q` passes for the whole suite (207 baseline + your new tests).
3. No new dependency; stdlib only.
4. No banned words; inferences labelled `(best guess)`.
5. Never touch the stale `src/lullaby/`.
6. Output one line: what changed.
