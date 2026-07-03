# Remaining confirmed bugs — subsystem batches

## Goal
Fix the 23 remaining CONFIRMED bugs from the two-engine code review (the 5 safety-tier bugs
are already done on branch codex/safety-alerts). Grouped into file-disjoint batches so each
can be implemented and tested independently. Every behaviour on an unrelated path must stay
identical, and the full test suite must stay green with a focused new test per fix.

## Global constraints
- Surgical: touch only what each fix needs. No refactors/renames/reformatting beyond the fix.
- Preserve every "best-effort, never raise into the monitoring/detection loop" property.
- No new third-party deps. No new config keys unless a fix is impossible without one (then
  minimal + defaulted + documented in config.py and the TOMLs).
- Python 3.11-3.14. Match existing style. Run tests with
  `/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q` (fallback
  `/opt/homebrew/bin/python3.11 -m pytest -q`).
- Do NOT run git. Leave changes in the working tree only.

---

## BATCH S — soothe playback correctness (src/beddington/soothe.py)

### S1 (#13) soothe.py ~62,107,157 — shared PID file lets one process kill another's playback
Every SubprocessSoothePlayer defaults to the SAME pid file (`~/.config/beddington/soothe-player.json`).
`stop_all()` SIGTERMs any remembered non-child pid whose command line still matches the sound
path — so the monitor process kills the dashboard's intentionally-playing sound (and vice
versa). Two distinct Beddington processes (live-view dashboard, monitor pipeline) run at once.
Fix: give the PID file a per-ROLE default so a process only ever reclaims ITS OWN orphans, not
a sibling's live playback. Add an optional role/pid-file parameter to SubprocessSoothePlayer /
_default_soothe_pid_file (keep the BEDDINGTON_SOOTHE_PID_FILE env override winning). The
dashboard player and the pipeline player must resolve to DIFFERENT default files. Cross-process
`stop_all()` must never signal a process it did not start. Keep single-process orphan-reclaim
across restarts working (a monitor restart still reclaims a monitor orphan).

### S2 (#14) soothe.py ~208 — PID file written non-atomically and clobbered
`_write_soothe_pid_file` uses `path.write_text()` (truncate-then-write); a concurrent reader can
get a torn/empty file -> JSONDecodeError -> silently `()`. Fix: write atomically (mkstemp in the
same dir + `os.replace`, the pattern already used for autosoothe.json). With S1's per-role files
the cross-process clobber largely dissolves, but the atomic write is still required.

### S3 (#15) soothe.py ~536 — failed preset switch leaves silence then spams
`_switch_if_due` calls `self.player.stop_all()` (536) BEFORE `self.player.play(step)` (537); if
play fails it emits `soothe_switch_failed` but does NOT advance state, so the due condition stays
true and it retries every window (killing sound each time). Fix: on a failed switch, do NOT leave
the nursery silent — keep/restore the previously-playing preset — and do NOT retry every window
(advance the switch schedule / add a backoff) so one failure does not spam-stop audio. A
successful switch must behave exactly as today.

Tests: extend tests/test_soothe.py — per-role pid-file isolation (a second player with the
default does not kill the first's remembered process), atomic write survives a concurrent read,
and a failing switch keeps the prior sound and does not re-fire every window.

---

## BATCH L — live-view server hardening (src/beddington/liveview.py)

### L1 (#4) liveview.py ~855 — busy-spin at 100% CPU per viewer when the active camera dies
In dual-camera mode, when the active mode's FrameBroker is closed but another broker is still
alive, the stream loop at ~855 spins immediately (wait_for_frame returns None at once) without
breaking or backing off. Fix: detect the active broker being closed and either end that client
stream cleanly (return) or back off, so a dead active camera does not peg a core per viewer.

### L2 (#5) liveview.py ~742 — unauthenticated slow-loris (no header read timeout)
The server sets no accept/read timeout; a client that drips request headers ties up a handler
thread/FD indefinitely, before auth. Fix: apply a bounded read timeout to incoming connections
(e.g. a socket timeout on the handler before/at header read) so slow header senders cannot
exhaust threads/FDs. Do not break the legitimate long-lived `/stream.mjpg` streaming path
(which sets its own timeout after dispatch).

### L3 (#7) liveview.py ~118,745 — non-ASCII token crashes the handler instead of 401
`_provided_token()` returns the raw query token; `is_authorised()` passes it to
`hmac.compare_digest()`, which raises TypeError on a non-ASCII str -> 500/crash instead of 401.
Fix: treat a token that cannot be compared (non-ASCII / encoding error) as simply unauthorised
(return 401), never a crash.

Tests: extend tests/test_liveview.py — a non-ASCII token yields 401 (not an exception); a
slow/partial header connection is bounded by timeout; (L1) a closed active broker does not loop
forever (assert the stream generator ends / does not spin).

---

## BATCH A — assistant voice routing (src/beddington/assistant.py)

### A1 (#24) assistant.py ~515 — "turn the music off" not recognised, then resumes
`_SOOTHE_STOP_WORDS` has the contiguous phrase "turn off" but "turn the music off" does not
contain it, so it is neither dispatched as stop nor caught by `looks_like_soothe_control`, and
the ducked track resumes after the utterance. Fix: recognise natural stop phrasings like "turn
the music off" / "turn it off" as a soothe STOP command (and include them in
looks_like_soothe_control) so the sound stops and does not resume. Do not over-match unrelated
"off" utterances (e.g. "turn off the light" is not a soothe command — scope to music/sound/noise
/ soothe targets).

### A2 (#25) assistant.py ~67,989 — "how is the baby's room?" answers with vitals
`_BABY_VITALS_PHRASES` includes "how is the baby", and `_mentions()` substring-matches, so "How
is the baby's room?" hits the baby-vitals branch before the room-overview branch. Fix: a
room/environment question must route to the room overview, not vitals. Make the room-overview
match take precedence when the utterance mentions room/environment, or tighten the vitals phrase
so "...room" does not match it.

Tests: extend tests/test_assistant.py — "turn the music off" stops soothe and is treated as
soothe control; "how is the baby's room?" returns the room overview, not breathing/heart data.

---

## BATCH N — narration + grounding (src/beddington/narrator.py, src/beddington/grounding.py)

### N1 (#30) narrator.py ~164,368,387 — TTS/playback subprocesses have no timeout
`speak()`, `_synthesise_piper`, `_synthesise_espeak` call `subprocess.run(check=True)` with no
`timeout=`. A held ALSA/Pulse device or a stalled piper load hangs the run forever after
monitoring completes. Fix: add a sensible `timeout=` to each (and treat a timeout as a clean
"not spoken"/"tts_failed", never a crash), matching how narrate()'s HTTP call already uses a
timeout.

### N2 (#31) narrator.py ~220 — sound diary counts overlapping windows as occurrences
`_sound_facts` counts each `sound_observed` event, but during a focus window every ~0.49s hop is
classified, so one continuous 10s coo becomes ~20 "times". Fix: collapse contiguous
same-label sound_observed events (e.g. count distinct runs, or de-dupe events within a small time
gap) so the parent-facing "heard N times" reflects occurrences, not analysis windows. Keep the
plain (non-focus) diary counts unchanged.

### N3 (#26) grounding.py ~171 — "no one" parsed as the number 1
`_number_values()` maps "one" -> 1 unless preceded by "little"; source text "no one"/"no-one"
then contributes a spurious numeric 1, licensing a fabricated count in narration. Fix: do not
treat the "one" in "no one"/"no-one"/"nobody" as the number 1.

### N4 (#28) grounding.py ~186 — decimal.InvalidOperation from quantize() crashes narration
`_normalise_number` only catches InvalidOperation from `Decimal(...)` construction; the later
`normalize()`/`quantize()` on a 29+-digit integer can raise InvalidOperation uncaught. Fix:
guard the quantize/normalize path too so a pathological number degrades gracefully (skip/keep as
text), never crashing the narrator.

Tests: extend tests/test_narrator.py and tests/test_context.py (or test_history_questions) —
a hung player is bounded (mock a slow subprocess -> timeout handled), one continuous coo across a
focus window is reported once/collapsed, "no one" does not add a numeric 1, and a 30-digit number
does not crash grounding.

---

## BATCH C1 — config + intent + notifications (src/beddington/config.py, intent.py, notifications.py)

### C1a (#33) config.py ~222-235,496-532 — bool() coercion turns "false" into True
TOML boolean loads use raw `bool(value)`, so a quoted `"false"` (or any non-empty string) becomes
True. Fix: coerce booleans string-aware (reuse the `_env_bool` logic / accept real bools and
"true"/"false"/"0"/"1" case-insensitively) for the TOML boolean keys. Keep genuine bool inputs
working.

### C1b (#29) intent.py ~202-239, config.py LlmTranslatorConfig — nine tuning keys unreadable
intent.py reads intent_*/lead_*/soothe_intent_* via getattr defaults, but LlmTranslatorConfig /
`_load_llm_translator` only define/load `enabled`, and the TOMLs only expose
`[assistant.llm_translator].enabled`, so the knobs can't actually be set. Fix: EITHER define +
load these keys in LlmTranslatorConfig and the TOML loader (with the same defaults intent.py uses)
so they are settable, OR if they are vestigial, remove the dead getattr reads. Prefer making them
settable if intent.py genuinely uses them; document the choice in your summary.

### C1c (#3) notifications.py ~31,39 — desktop notify subprocess has no timeout, blocks the loop
`LocalNotifier._desktop()` runs osascript/notify-send with no `timeout=`, inline in the
per-window loop; a wedged notifier freezes cry scoring/soothe during active crying. Fix: add a
bounded `timeout=` to both subprocess.run calls and treat a timeout as a failed desktop send
(return False), never raising into the loop.

Tests: extend tests/test_config.py (string "false" -> False; the new translator keys load),
tests/test_intent.py (a set tuning key is honoured, if made settable), tests/test_notifications.py
(a slow desktop notifier is bounded and returns desktop:false).

---

## BATCH C2 — store + llm + logging (src/beddington/sensor_store.py, llm.py, logging.py)

### C2a (#32) sensor_store.py ~117 — downsampling drops the NEWEST points
`series()` does `rows = rows[::step]`, which keeps index 0,step,... and can drop up to step-1 of
the most-recent rows. Fix: downsample so the LATEST row is always included (e.g. sample from the
end, or always append the final row), so graphs/staleness reflect the freshest data.

### C2b (#34) llm.py ~68-82,60-65 — empty LLM content replaces the good digest; bad JSON escapes
`_extract_content` returns "" for empty content and run_pipeline assigns it over the deterministic
digest; also `polish_digest` only catches URLError, so malformed JSON / read timeouts escape. Fix:
if the LLM returns empty/whitespace content, KEEP the deterministic digest (do not blank it); and
catch JSON decode / timeout / value errors in polish_digest so any LLM failure falls back to the
deterministic digest (the pipeline already fails-open, keep that contract).

### C2c (#35) logging.py ~62-70,47 — failed soothe labelled "dry run"; fault kinds dropped
`_readable_log` labels a `soothe_attempted` with played=false as an intentional "dry run", but a
real failed playback emits `soothe_unavailable`; and `_readable_log` has no branch for
soothe_unavailable / soothe_switch_failed / sensor_unavailable, so faults vanish from the readable
log. Fix: only call it a "dry run" when it truly was one (no failure), and render the fault event
kinds (soothe_unavailable, soothe_switch_failed, sensor_unavailable) as visible fault lines in the
readable night log.

Tests: extend tests/test_sensor_store.py (latest point retained after downsample),
tests/test_digest or a new llm test (empty LLM content keeps the deterministic digest; bad JSON
falls back), tests/test_night_digest or a logging test (a failed soothe is not called a dry run;
fault kinds appear in the readable log).

---

## BATCH P — ops scripts (scripts/*.sh)

### P1 (#37) scripts/overnight_smart_loop.sh:12 (+ fix_loop.sh, soothe_loop.sh, soothe_v2_loop.sh,
sound_loop.sh, voice_v2_loop.sh) — REPO hardcoded to a dead worktree
`REPO="/Users/elzekmo/Code/Labie/.claude/worktrees/flamboyant-kilby-76d688"` no longer exists, so
every loop exits immediately; and if that path is ever recreated the loop would push THAT tree to
main. Fix: derive REPO from the script's own location (e.g. `REPO="$(cd "$(dirname "$0")/.." &&
pwd)"`) in all six scripts.

### P2 (#38) scripts/overnight_smart_loop.sh:~100 (+ siblings) — no clean-tree preflight; add -A to main
The loop treats any non-empty `git status --porcelain` as "codex made changes", then `git add -A`
commits+pushes everything to main, so pre-existing WIP/secrets get published and the no-change
gate is defeated. Fix: add a clean-working-tree preflight (abort if `git status --porcelain` is
non-empty before starting), and/or stage only the paths the unit is expected to touch instead of
`git add -A`. Apply to all six loop scripts. Keep behaviour otherwise identical.

Tests: shell scripts have no unit tests; keep changes minimal and note manual-verification steps
in your summary (e.g. `bash -n` syntax check each script).

---

## BATCH V — cli soothe-outcome + wake timer (src/beddington/cli.py, src/beddington/soothe.py finish)
(Run AFTER Batch S, since it also touches soothe.py.)

### V1 (#18) cli.py ~75,521 + soothe.py finish ~350-371 — successful soothe logged as failure
`_SOOTHE_FAILURE_EVENTS={"soothe_unresolved"}` and `_record_soothe_outcomes` writes success=False
for it. But SootheController.finish emits `soothe_unresolved` even when the cry already ended and a
pending settled/quiet resolution is merely waiting out hold_after_stop/min_play (600s), i.e. a
SUCCESS. Fix: distinguish "ended while a positive resolution was pending" from a genuine
unresolved failure — either finish emits a neutral/success-ish event for the pending-resolution
case, or `_record_soothe_outcomes` does not count soothe_unresolved as a failure when it carries a
pending-resolution reason. A genuinely unresolved cry (no pending positive resolution) must still
be recorded as a failure. Do not poison the learner with false failures.

### V2 (#36) cli.py ~911 — pending-wake timer resumes soothe after an explicit stop
When a bare wake word ducks the music, `pending_wake_until`/`pending_wake_soothe` are armed for 6s
and only cleared in the no-wake-word follow-up branch. A follow-up that itself contains the wake
word (e.g. "Hi Beddington, stop the music") executes the stop but leaves pending state armed, so
the ~6s timeout later resumes the sound the parent just stopped. Fix: clear the pending-wake state
whenever a soothe-affecting command (stop/play/next/switch) is executed on the follow-up,
including the wake-word-follow-up path, so the timer never resumes a sound the user just
stopped/replaced.

Tests: extend tests/test_cli.py — a run that ends inside the hold window after a successful settle
is NOT recorded as a soothe failure; and a wake-word follow-up "stop" clears pending-wake so the
timer does not resume playback.

---

## Non-goals (do NOT touch)
- The safety-alerts fixes (already on codex/safety-alerts): the alert token path, the notification
  cooldown bookkeeping (state.py/pipeline.py), the radar reader, the systemd units. Do not modify
  state.py or the deploy units in this batch.
- Any PARTIAL-only finding (e.g. soothe volume for pw-play/ffplay, the "switch off"->next narrow
  case, vitals-followup) unless explicitly listed above.
- Reformatting, type-hint sweeps, docstring rewrites, dependency bumps.

## Risk areas (aim the review here)
- BATCH S: cross-process kill semantics — the fix must not regress single-process orphan reclaim,
  and must never leave the nursery silent on a failed switch.
- BATCH A: over-matching "off"/"stop" so unrelated utterances get treated as soothe control.
- BATCH V: mis-classifying a genuine unresolved cry as success (under-reporting a real failure to
  the learner) — the neutral case must be ONLY the pending-positive-resolution one.
- BATCH C2b: never blank the digest; always fall open to the deterministic one.
- BATCH P: the clean-tree preflight must not block a legitimate run that only has the unit's own
  changes.
