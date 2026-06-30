# Beddington assistant expansion — plan for Codex to review + execute

> **Workflow:** Codex reviews this plan critically, then implements all four features
> with tests on the repo, runs the suite, and commits. Codex does NOT touch the
> Raspberry Pi (no access) — Claude deploys after. Repo: Python package
> `src/beddington/`, tests `tests/`, run with `uv run --extra dev pytest -q`.

## NON-NEGOTIABLE SAFETY INVARIANTS (carry over — do not weaken)
1. **Never fabricate a sensor reading.** The deterministic brain stays the fact source.
2. **No reassurance / no medical claim about the baby.** Never say the baby is
   safe / asleep / sleeping / healthy / fine / well / okay / normal / calm /
   settled / content / at peace, and never give medical advice. (Enforced by
   `tests/test_assistant.py` `_REASSURANCE` set + `persona._BANNED_WORDS`.)
3. **The cry→alarm reflex (`pipeline.run_pipeline`) is untouched.**
4. **LLM persona only RE-VOICES** the deterministic answer (grounded restyle in
   `persona.paddingtonise`). New "verbatim" answers (vitals, FAQ, settled, night)
   must NOT be sent to the LLM — they are spoken exactly as written.
5. Offline only — no network calls, no internet lookups.

## Shared refactor (do FIRST) — `classify_question`
The listen loop needs to know the matched intent (to gate restyle + drive
follow-up memory). In `src/beddington/assistant.py`:
- Add `def classify_question(question: str) -> str | None` returning the intent key
  using the SAME routing logic `answer_question` already uses, one of:
  `"temperature" | "humidity" | "pressure" | "air" | "light" | "presence" |
  "people" | "vitals" | "unsupported_vitals" | "distance" | "overview" |
  "time" | "date" | "faq" | None`.
- Refactor `answer_question` to call `classify_question` internally (single source
  of truth for routing) so behaviour is unchanged for existing tests. If a clean
  refactor is risky, instead expose `classify_question` that mirrors the routing
  and add a test asserting it agrees with `answer_question` on a sample set.
- Existing 200+ tests must still pass.

## Feature 1 — Time / date  (safe, offline)
`src/beddington/assistant.py`:
- `_TIME_WORDS = ("time", "clock", "o'clock")`; `_DATE_WORDS = ("date", "what day", "which day", "today's date")`.
- `def _time_phrase(now: datetime | None = None) -> str` — `now = now or datetime.now()`.
  Return spoken digits so the persona's number-check can anchor it, e.g.
  `"It's about 9:20 in the evening."` Round minute to nearest 5. Period =
  morning(<12)/afternoon(<18)/evening(else). 12-hour clock.
- `def _date_phrase(now: datetime | None = None) -> str` — e.g.
  `"Today is Monday the 29th of June."` (weekday, ordinal day, month name).
- Route in `answer_question`/`classify_question`: time question → `"time"`,
  date question → `"date"`, BEFORE the fallback. Guard against false matches
  (use `_mentions` whole-word like the rest).
- Tests (`tests/test_assistant.py`): `_time_phrase(fixed datetime)` and
  `_date_phrase(fixed datetime)` exact strings; `answer_question("what's the time", {})`
  is not the fallback and contains a digit; date question routes to date.

## Feature 2 — Light follow-up memory  (in the listen loop, grounded)
Goal: after answering a topic, a bare follow-up like "and now?" / "again?" re-answers
the SAME topic with fresh readings. Each turn still uses the wake word.
`src/beddington/assistant.py`:
- `_FOLLOWUP_CUES = ("and now", "what about now", "how about now", "again", "and you", "now")`.
- `def resolve_follow_up(question: str, last_topic: str | None) -> str | None`:
  return `last_topic` IFF `classify_question(question) is None` AND the question
  matches a follow-up cue AND `last_topic` is a re-answerable reading topic
  (temperature/humidity/pressure/air/light/presence/people/distance/overview);
  else `None`.
`src/beddington/cli.py` `_listen_assistant_command`:
- Track `last_topic: str | None = None`, `last_topic_at: float = 0.0`.
- For each question: `topic = classify_question(question)`. If `topic is None`,
  try `follow = resolve_follow_up(question, last_topic if now-last_topic_at < 30 else None)`;
  if `follow`, synthesise the question for that topic (e.g. re-call
  `answer_question` with a canonical phrase per topic, or expose a helper
  `answer_topic(topic, snapshot)`), and set `topic = follow`.
- After answering, if `topic` is a reading topic, set `last_topic = topic`,
  `last_topic_at = now`.
- NOTE: reuse `time.monotonic()` already used in the loop. Keep ≤ ~30 s memory window.
- Tests (`tests/test_assistant.py`): `resolve_follow_up("and now?", "humidity")
  == "humidity"`; returns `None` when last_topic is None, when the question has
  its own topic, or when last_topic isn't a reading. (Loop wiring is hard to unit
  test; a light test on `resolve_follow_up` is enough.)

## Feature 3 — "How long settled" (history; NEVER "asleep")
Answered in the loop from persisted history (`night_store: SensorStore`), like the
night digest — NOT in `answer_question` (snapshot-only). HONEST about the data:
the bear sees presence/stillness, not sleep, and has NO cry-event store in this
loop, so it must NOT claim "asleep" and must NOT claim "no crying" (unverifiable).
`src/beddington/night_digest.py`:
- `def summarise_settled(series: list[dict], now_ts: float) -> str`:
  From the recent presence (+ any movement/restless best-guess already derived in
  this module) compute how long someone has been continuously present and mostly
  still. Phrase e.g. `"Someone's been in the room and mostly still for about 2
  hours — settled, best I can tell."` If presence is intermittent: `"It's been
  on and off — someone around about 40% of the last 2 hours."` If not enough
  history: `"I don't have enough history yet to say."` BANNED words must not
  appear (reuse the `tests/test_night_digest.py` `_BANNED` guard). Never
  "asleep/sleeping/slept". Prefer "quiet"/"still"/"calm" wording; if "settled" is
  used it describes movement, not sleep.
`src/beddington/cli.py`:
- `is_settled_question(q)` (add to assistant.py): matches "how long settled",
  "how long quiet", "how long still", "has it been quiet", "how long has the
  baby been settled/quiet/still", "any crying" (→ honest "I can't track crying
  history here, only live"). Route in the loop BEFORE `answer_question`, using
  `night_store.series(...)` → `summarise_settled`. Spoken VERBATIM (no restyle).
- Tests (`tests/test_night_digest.py`): `summarise_settled` on a synthetic series
  (continuous presence) returns a duration + no banned/sleep words; empty series
  → the "not enough history" line; `assert "asleep" not in out and "sleeping" not in out`.

## Feature 4 — Curated baby FAQ (vetted facts, spoken verbatim, NOT the LLM)
New file `src/beddington/baby_faq.py`. A small dict of vetted answers; NO LLM, NO
invented facts. Each answer is factual, carries "every baby is different", and the
module is framed as general info, not medical advice.
- `def match_baby_faq(question: str) -> str | None` — keyword match (whole-word /
  fuzzy like `assistant._mentions`), returns the vetted answer or `None`.
- USE EXACTLY THESE VETTED ANSWERS (keep the age ranges; minor wording ok):
  - sit / sitting → "Most babies sit with support around 4 to 6 months, and on
    their own around 6 to 8 months. Every baby is different, and I'm not a doctor."
  - roll / rolling → "Babies often start rolling over around 4 to 6 months. Every
    baby is different."
  - crawl / crawling → "Many babies start crawling around 7 to 10 months. Every
    baby is different."
  - walk / walking / steps → "First steps often come around 9 to 15 months. Every
    baby is different."
  - teeth / teething → "First teeth usually appear around 6 months, though
    anywhere from 3 to 12 months is normal."
  - talk / first words → "First words often come around 12 months. Every baby is
    different."
  - smile / smiling → "Babies often start smiling socially around 6 weeks to 2
    months."
  - solids / solid food / weaning → "Solids are usually introduced around 6
    months — but do check with your health visitor."
  - room temperature / how warm should the room be → "A comfortable room for a
    baby is usually around 16 to 20 degrees Celsius."
- `_FAQ_NO_MATCH = "That's a good one for your doctor or health visitor. I can
  really only tell you about the room and your baby's surroundings."`
- Routing: in `answer_question`/`classify_question`, AFTER the sensor/time/date
  intents and BEFORE the generic `_FALLBACK`, call `match_baby_faq`. If it returns
  text → intent `"faq"`, answer = that text. Only use `_FAQ_NO_MATCH` when a baby
  topic was detected but isn't in the FAQ (a small `baby_topic` detector decides
  this); otherwise unrecognised speech keeps the normal `_FALLBACK`. Keep it
  conservative to avoid hijacking sensor questions.
- Tests (`tests/test_baby_faq.py` new): each keyword → its vetted answer; the age
  numbers are present; an unrelated question → `None`.

## Restyle gating (ties Features 3 & 4 + vitals to "verbatim")
`src/beddington/cli.py` `_listen_assistant_command`, at the single persona chokepoint:
- `NO_RESTYLE_INTENTS = {"vitals", "unsupported_vitals", "faq"}` (settled + night
  are already answered outside `answer_question` and spoken verbatim).
- Compute `intent = classify_question(question)` (already needed for follow-up).
  `if intent in NO_RESTYLE_INTENTS: answer = <plain>` (skip `paddingtonise`);
  else `answer = paddingtonise(answer, speak_config)`.
- Keep `persona.is_medically_sensitive` as the inner backstop (defence in depth).

## Test + commit checklist (Codex)
1. `uv run --extra dev pytest -q` — ALL green (existing + new).
2. Keep changes additive; do not alter the cry pipeline or persona validation core.
3. One commit per feature (or one well-described commit), Conventional Commit
   style, ending with `Co-Authored-By: WOZCODE <contact@withwoz.com>`.
4. Do NOT push, do NOT deploy, do NOT touch config/demo.toml or any Pi path.
   Leave `ASSISTANT-EXPANSION-PLAN.md` untracked (Claude removes it).
5. If any step conflicts with a SAFETY INVARIANT, STOP that part and report it
   instead of implementing it.

## Deploy (Claude, after Codex) — not for Codex
rsync changed `src/beddington/*.py` to `lab-pi:Labie/src/beddington/`, restart
`paddington`, smoke-test by voice.
