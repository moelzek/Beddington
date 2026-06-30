# Beddington — soothe v2 (codex build spec)

You are an autonomous coding agent on **Beddington** (package `beddington` at
`src/beddington/`; tests in `tests/`). Implement **only the unit you are told**,
keep the WHOLE suite green (`pytest -q`), stdlib only, no new dependencies. Never
touch the stale gitignored `src/lullaby/`. No banned words; inferences "(best
guess)". Do NOT change the deterministic cry DETECTION or the alarm/notify path —
only the soothing-sound behaviour.

## Context (observed on real hardware)
`SootheController` (`src/beddington/soothe.py`) plays a soothe sound when a
sustained cry triggers (`escalation_due`). It receives the continuous cry tracker
events (`cry_started` / `cry_ended`) on every `observe()` call, so it always knows
whether the baby is currently crying — no need to pause the sound to listen.

Today, with `soothe.quiet_check` ON, the controller PAUSES the sound ~4s every ~15s
to "listen back" (`soothe_quiet_check_started`). On the live device this is audible
as the **sound cutting out every few seconds**. `soothe.min_play_seconds` (=600)
already enforces a 10-minute minimum, and outcomes are recorded under the preset
key via `_record_soothe_outcomes` (`src/beddington/cli.py`).

Mo's desired behaviour:
1. **No cutting** — the soothe plays continuously.
2. **Switch sound after 5 min still-crying** — if still crying 5 min into a sound,
   switch to the next-best sound by the learning.
3. **Hold 10 min after he STOPS** — keep soothing until 10 minutes after the last
   cry (extend while crying continues), then stop and record the outcome.
4. **Voice stop** — "Hi Beddington, stop" (stop soothe/sound/music) stops it.
5. Learning stays smart explore-then-settle (`best_preset` already favours
   less-tried sounds under `min_samples`, then the highest success rate).

## Config (add under `[soothe]`, with short comments, in BOTH config/default.toml
and config/pi-product.toml; add fields to SootheConfig + loader + `_validate`):
- `hold_after_stop_seconds: float = 600.0`  (keep soothing until 10 min after the
  last cry; validate >= 0)
- `escalate_after_seconds: float = 300.0`  (switch sound after this long still
  crying; validate >= 0)
Keep `min_play_seconds` as an absolute floor.

---

### W1 — continuous playback (kill the cutting)
Drive "still crying / stopped" purely from the continuous `cry_started`/`cry_ended`
tracker events; do NOT pause the sound to listen. In `config/pi-product.toml` set
`[soothe.quiet_check] enabled = false`. Ensure no `soothe_quiet_check_started`
pause events are emitted while soothing in the normal path. Add/adjust tests so a
soothing episode plays continuously (no pause events) and still tracks crying.

### W2 — hold until 10 min after crying STOPS
Track the offset of the most recent cry while active. The soothe stays active while
crying; after the last `cry_ended`, keep playing until `hold_after_stop_seconds`
have elapsed with no further cry, THEN stop (`player.stop_all()`) and emit
`soothe_settled` (record the sound that was playing as a SUCCESS via the existing
outcome path). If crying resumes during the hold, cancel the countdown and keep
soothing. Also respect `min_play_seconds` as a floor. Acceptance test (synthetic
offsets): cry at t=0 triggers soothe; `cry_ended` at t=30s; assert it keeps playing
and only settles at >= 30s + hold_after_stop_seconds; if a new `cry_started`
arrives during the hold, it does not settle.

### W3 — switch sound after 5 min still-crying
While the baby is still crying and `escalate_after_seconds` have elapsed since the
current sound started, switch to the **next-best** preset chosen by
`beddington.soothe_memory.best_preset` over the available presets EXCLUDING the
current one (fall back to any other preset if no data). Stop the old playback,
start the new sound, emit a `soothe_switched` event (details: from, to). Continue
switching every `escalate_after_seconds` of continued crying through the ranked
sounds. Acceptance test: still-crying past escalate_after_seconds -> a
`soothe_switched` event to a different preset; no switch if crying stops first.

### W4 — voice stop
Extend the assistant voice command so "Hi Beddington, stop" / "stop the
soothe|sound|music|noise" stops the active soothe. Build on the existing
`match_soothe_command` (`src/beddington/assistant.py`) which already parses
play/stop; ensure a recognised stop command halts the active auto-soothe playback
(the same player the auto-soothe uses) and is safe when nothing is playing. Add a
test for the stop-intent parsing and that it triggers a stop.

## Per-unit checklist
1. Only this unit's scope; stdlib only; whole suite green with `pytest -q`.
2. Add the acceptance test(s) described (they must fail on current code).
3. Don't change cry detection/alarm; don't touch `src/lullaby/`.
4. Output one line of what changed.
