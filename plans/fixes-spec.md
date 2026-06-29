# Beddington fixes — codex build spec (found by a live Raspberry Pi test)

You are an autonomous coding agent on **Beddington** (package `beddington`, at
`src/beddington/`; CLI `beddington`; tests in `tests/`). You are invoked one
**unit** at a time by a driver. Implement **only the unit you are told**, keep the
WHOLE suite green (`pytest -q`), stdlib only, no new dependencies. Never touch the
stale, gitignored `src/lullaby/`.

A real run on the Pi (mic + speaker + llama3.2:1b via Ollama) exposed two bugs the
mocked unit tests missed. Fix them with regression tests that would FAIL on today's
code and PASS after your fix.

## Safety rules (unchanged)
No banned words (asleep/safe/healthy/fine/normal/well/breathing-as-vital). Label
inferences "(best guess)". Deterministic core unchanged. The local LLM is optional
and must degrade gracefully, and it must NEVER introduce facts of its own.

---

### F1 — soothe-memory learning is inert (identity mismatch)

**Evidence from the Pi:** an outcome was stored as `sound_name = "white noise"`
(the preset's *display name*, `SootheStepConfig.name`, taken from the
`soothe_attempted` event `details["name"]` in `_record_soothe_outcomes`,
`src/beddington/cli.py`). But `best_preset` in `src/beddington/soothe_memory.py`
ranks over `presets` **keys** (e.g. `"white_noise"`) — `names = sorted(presets)`.
`"white noise" not in {"white_noise", ...}` -> every recorded outcome is skipped ->
the learning never changes the chosen preset.

**Fix:** make the recorded identifier and the ranking identifier the SAME stable
key (the preset key, e.g. `white_noise`). Record outcomes under the preset key
(map display-name->key via the configured presets where the outcome is recorded, or
thread the key through), and make sure `best_preset` and the night-digest
`_sound_label` still work. Do not change the deterministic cry/soothe behaviour.

**Acceptance test (new, end-to-end - must fail on current code):** in a test,
build the SAME events the pipeline emits (`soothe_attempted` with
`details["name"]` = a preset's display name, followed by `soothe_quiet_confirmed`),
feed them through the REAL recording path (`_record_soothe_outcomes` /
`_record_run_soothe_outcomes`) into a real `SensorStore`, then read them back and
call `best_preset(store.outcomes_since(0), presets, min_samples, default)` with the
real `presets` mapping - assert the repeatedly-successful preset IS returned. Also
keep/extend a test proving a learned winner is chosen over the configured default.

---

### F2 — narrator (and persona) hallucinate facts (safety)

**Evidence from the Pi:** the deterministic digest was *"Beddington detected 1
sustained crying episode ... ~2 seconds ... 1 soothe preset ... 0 notifications."*
The llama narration (`narrate()` in `src/beddington/narrator.py`) ADDED invented
facts: *"room temperature ~22C, relative humidity 60%, the parent's presence
remained constant"* - none of which were in the source (no sensors enabled).
Confirmed by re-running with the narrator off.

**Fix:** the narrator must stay ON by default but be **grounded** - the LLM may
only re-word the deterministic text it is given; it must never introduce new facts.
Add a validation/grounding pass on the LLM output: if the output introduces
information not supported by the source digest - in particular any **number/units**
(C, %, bpm, cm, lux, etc.) or any sensor/presence/medical claim NOT present in the
source - discard the LLM output and fall back to the deterministic digest (or strip
the offending content). Apply the same guard to the persona re-voicing path
(`src/beddington/persona.py`) which also re-voices answers via the LLM. Keep the
graceful fallback when Ollama is absent.

**Acceptance tests (new, with a fake LLM via monkeypatch/injection):**
1. fake LLM returns text that adds an invented number/claim absent from the source
   -> `narrate()` returns the deterministic fallback (no invented number leaks).
2. fake LLM returns a faithful re-wording (no new facts) -> that text is used.
3. persona path: fake LLM tries to add a fact/number to an answer -> the grounded
   answer is returned unchanged (persona may never change or add a fact/number).
4. Ollama unavailable (caller raises) -> deterministic fallback, as today.

---

## Per-unit checklist
1. Only this unit's scope, only under `src/beddington/`, `tests/`, `config/`.
2. Add the regression test(s) described; the whole suite passes with `pytest -q`.
3. Stdlib only; no new dependency. No banned words; inferences "(best guess)".
4. Never edit the stale `src/lullaby/`.
5. Output one line of what changed.
