# Review verdict — remaining-fixes batch (23 bugs)

Branch: `codex/remaining-fixes` (base `claude/sad-cannon-7dff4f`)
Implementer: OpenAI Codex (8 disjoint-file batches) + Claude hand-fixes. Reviewer: Claude +
two adversarial workflows (per-batch reviewers + regression + test-quality + verify), plus one
Codex repair pass that timed out (replaced by hand-fixes). Tests: **382 passed** (was 355; +27).

## Per-batch verdict (all CONFIRMED correct after fixes)

| Batch | Files | Fixes | Verdict |
|---|---|---|---|
| S | soothe.py | #13 per-role PID file, #14 atomic write, #15 failed-switch restore+backoff | CORRECT (see fixes below) |
| L | liveview.py | #4 camera-death no-spin, #5 header read timeout, #7 non-ASCII token → 401 | CORRECT (1 caveat) |
| A | assistant.py | #24 "turn the music off" stops, #25 room Q → room overview | CORRECT (after A1 fix) |
| P | scripts/*.sh | #37 REPO from script dir, #38 clean-tree preflight + scoped staging | CORRECT (2 caveats) |
| N | narrator.py, grounding.py | #30 TTS timeouts, #31 collapse sound windows, #26 "no one"≠1, #28 decimal guard | CORRECT |
| C1 | config.py, intent.py, notifications.py | #33 bool coercion, #29 tuning keys settable, #3 notify timeout | CORRECT (1 caveat) |
| C2 | sensor_store.py, llm.py, logging.py | #32 keep newest point, #34 keep digest on empty LLM, #35 dry-run label + fault kinds | CORRECT |
| V | cli.py, soothe.py finish | #18 success-not-failure, #36 wake timer no-resume | CORRECT (after V1 fix) |

## BLOCKING found in review → all fixed

1. **A1 pronoun over-match** (assistant.py). `_SOOTHE_OFF_TARGETS` included bare `"it"/"that"`,
   so "turn it off" / "turn that off" force-stopped soothing regardless of referent (a lamp, a
   heater). Wrongly stopping the baby's sound is worse than not matching. **Fix:** dropped the
   pronouns; explicit nouns ("turn the music off") still work. Tests updated to assert non-match.
2. **finish() false-success** (soothe.py). A Claude hand-fix (pending_before snapshot) meant to
   fix #18's quiet case could resurrect a dropped pending-quiet resolution and record a
   genuinely still-crying/loud recording as `soothe_quiet_confirmed` — masking a real failure.
   Two reviewers confirmed. **Fix:** reverted to batch V's version, which errs toward
   `soothe_unresolved` (a spurious *failure*, the safe direction) and only when quiet_check is
   enabled — which no shipped config does. #18's common (settled) case remains correctly fixed.
3. **Failed-switch restore not verified** (soothe.py). On a failed preset switch, the restore
   `play(previous_step)` return was discarded and state asserted the prior preset was active. A
   doubly-broken backend → silent nursery, controller believes audio plays, no fault. **Fix:**
   check the restore result; if both the switch and the restore fail, emit `soothe_unavailable`
   so a human is alerted. New test covers it.

Plus a hand-added S3 backoff so a failed switch at `escalate_after_seconds=0` (valid config)
no longer kills audio and re-fires every window — `_switch_retry_after_offset` with a 5s floor,
reset on success and in `_reset()`. New test covers it.

## NON_BLOCKING caveats (ship, but know these — aim your Pi test here)

- **L2** (liveview.py): only `/stream.mjpg` bumps the read timeout to 20s after dispatch; every
  other endpoint (JSON polls, POSTs) now writes under the 5s header timeout. Self-healing (the
  dashboard just retries), but a big JSON payload over a weak LAN link could false-timeout mid-write.
- **V1 residual** (soothe.py): when `quiet_check.enabled=true` (no shipped config uses it), a
  quiet-confirmed soothe ending inside min-play is recorded as `soothe_unresolved` (a false
  *failure*). Safe direction; proper fix would pass the final window score (not the run peak) to
  `finish()` at pipeline.py — deferred.
- **C1b** (config.py): `LlmTranslatorConfig` carries the 9 tuning knobs but not model/host; the
  wiring copies them onto `narrator_config` (which has model/host) before use. Works; indirect.
- **P1/P2** (scripts): REPO derivation doesn't follow a symlinked script path (BASH_SOURCE is the
  symlink); a BLOCKED overnight unit leaves the tree dirty so a resume run now hard-aborts at the
  clean-tree preflight. Both are ops-script edges, not runtime code.
- **C2a** (sensor_store.py): just above `max_points` the returned point count drops sharply
  (ceil-step resolution quirk); newest point is always kept, so no correctness issue.

## Residual risk / Pi checks
Behaviour changes on soothe (PID isolation, failed-switch, finish), voice routing, live-view, and
sensors. Verify on the Pi: (a) dashboard-started music is NOT killed when a night monitor run
ends (per-role PID files); (b) "turn the music off" stops and stays stopped, "turn it off" does
NOT stop soothing, "how is the baby's room?" gives the room overview; (c) live-view survives a
camera death without pegging CPU and a phone on a weak link still loads the dashboard; (d) a
quoted `false` in a TOML boolean is now honoured. None of these were covered by tests before.
