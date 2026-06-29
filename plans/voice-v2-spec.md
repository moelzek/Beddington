# Beddington — voice v2 (codex build spec)

Autonomous agent on **Beddington** (package `beddington` at `src/beddington/`,
tests in `tests/`). Implement **only the unit you are told**, keep the WHOLE suite
green (`pytest -q`), stdlib (+ numpy only for asset generation) — no new
dependency. Never touch the stale gitignored `src/lullaby/`. No banned words;
inferences labelled "(best guess)". Don't change cry DETECTION or the alarm path.

## Where the voice loop lives
`src/beddington/cli.py` `listen-assistant` loop (~L838): `extract_wake_question`
(`ears.py`) gets the wake word; then `match_soothe_command` (`assistant.py`) →
`_soothe_via_dashboard`, or `is_night_question` → night digest, else
`answer_question(question, snapshot, llm_translator_cfg)` → `paddingtonise` → speak.
Soothe plays via `_soothe_via_dashboard(cmd)` (live-view HTTP player). Auto-soothe
on/off is the `autosoothe.json` state (`autosoothe.read_state`/`write_state`).
Sensor/cry history is in `SensorStore` (`sensor_store.py`); night recap uses it.

Each unit: add the described behaviour + deterministic tests that fail on today's
code. Keep it all on-device and deterministic; the LLM must never invent facts.

---

### VC1 — "I heard you" chime on the wake word
When the wake word is recognised (a question is extracted), play a short pleasant
chime BEFORE transcribing/answering, so the user knows it's listening. Add a tiny
`chime.wav` (~0.3s, gentle two-tone, 16 kHz mono 16-bit) generated in
`scripts/generate_soothe_assets.py` (reuse helpers; regenerate assets with the
numpy interpreter). Play it via the existing audio player. Add
`[assistant] chime_enabled = true` config (AssistantConfig + loader +
default.toml + pi-product.toml + demo.toml if present). Make sure the chime audio
is NOT transcribed as input (drop frames as the speak path already does). Off-switch
honoured. Tests: wake detected + chime_enabled -> chime play invoked (fake player);
disabled -> not played.

### VC2 — full voice control of soothing
Extend `match_soothe_command` (`assistant.py`) to recognise, case-insensitively:
- play a SPECIFIC sound by display name (any of the 12 presets, e.g. "play rain",
  "play ocean waves", "play the heartbeat") -> {action:play, preset:<key>}
- "stop" / "stop the sound|music|soothe|noise" -> {action:stop}
- "next" / "switch" / "try another" -> {action:next} (cli picks the next-best
  preset via soothe_memory.best_preset excluding current)
- "louder" / "quieter" -> {action:volume, dir:up|down} (cli applies a best-effort
  volume change to the playback; degrade gracefully if unsupported)
- "start watching for crying" / "stop watching" / "auto soothe on|off" ->
  {action:autosoothe, enabled:bool} (cli writes autosoothe.write_state)
Wire each new action in the cli soothe path. Map display names -> preset keys via
the configured presets. Tests: each phrase parses to the right command; unknown ->
None; the cli wiring for next/volume/autosoothe is covered.

### VC3 — follow-up questions (light conversation memory)
Give the assistant short multi-turn context so pronoun/topic follow-ups resolve.
Track the last answered intent; when the next question is a bare follow-up that
refers to it ("is that hot for a baby?", "is that ok?", "what about humidity?",
"and the humidity?"), resolve it to the right intent and answer deterministically
(reuse the existing per-intent phrases, which already include comfort notes). The
value ALWAYS comes from the deterministic sensor read — never invented. Keep it a
small, explicit carry-over (e.g. last intent + a follow-up detector), not a free LLM.
Tests: ask temperature, then "is that hot for a baby?" -> returns the temperature
comfort answer (not the fallback); "what about humidity?" after any reading ->
humidity answer.

### VC4 — history questions (counts + trends)
Add deterministic intents answered from the persisted history (the night store):
- "how many times did she cry tonight?" / "how many cries" -> count of cry episodes
  from the stored events/history for the night window.
- "is it getting colder/warmer / more humid?" / "is the temperature rising?" ->
  simple trend (compare the recent average vs earlier average from the sensor
  history) -> "best guess" phrase, no medical claim.
Wire into the assistant path (alongside is_night_question). If there isn't enough
history, say so plainly. Tests with seeded history: cry-count returns the right
number; a rising/falling series returns the correct trend phrase carrying
"(best guess)" and tripping no banned word.

## Per-unit checklist
1. Only this unit's scope; stdlib (+numpy for assets) only; whole suite green.
2. Deterministic; LLM never invents facts; no banned words; "(best guess)" on
   inferences.
3. Don't touch src/lullaby/. Output one line of what changed.
