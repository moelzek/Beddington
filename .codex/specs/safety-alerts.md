# Safety batch: reliable cry alerts, sensor freshness, and boot startup

## Goal
Close the five CONFIRMED-high bugs on the "wake the parent when the baby cries" path, so
that on a real Raspberry Pi: the LAN cry alert actually reaches the phone, a real cry is
never silently swallowed by the notification cooldown, the radar never reports stale data
as live, and both background services actually start after a reboot. Behaviour on every
other path must be unchanged.

## Files likely involved
- src/beddington/cli.py (token handoff: `_listen_assistant_command` ~800-825, `_fire_cry_alert`, `_resolve_live_view_token` ~1788-1815, `_read_live_view_token` ~1818-1827)
- src/beddington/state.py (CryEventTracker notification-cooldown bookkeeping)
- src/beddington/pipeline.py (run_pipeline notify dispatch, ~85-197)
- src/beddington/sensors.py (Mr60RadarReader `_run`/`_stream`/`read` ~189-260)
- deploy/beddington-assistant.service
- deploy/beddington-liveview.service
- tests/ (add one focused test per fix)

## The five fixes (each independently reviewable)

### FIX 1 — cry-alert token is read once and never refreshed (cli.py:812-814)
`_listen_assistant_command` builds `LiveViewNotifier(token=(_read_live_view_token() or ""))`
ONCE at startup. `LiveViewNotifier.notify()` short-circuits to `{"lan": False}` on an empty
token and never re-reads the file. If the assistant starts before the live-view token file
exists, alerts are silently dead for the whole session.
Required behaviour: every cry alert must use the CURRENT persisted token. Re-read the token
inside `_fire_cry_alert` (via `_read_live_view_token()`) and use it for that alert — so a
token created/changed after startup is picked up. Do not change `LiveViewNotifier`'s public
shape unless needed; refreshing `_alert_notifier.token` (or building a notifier per alert)
is acceptable. Keep the best-effort "never raise into the loop" property.

### FIX 2 — explicit `--token` is never persisted (cli.py:1791-1795)
`_resolve_live_view_token` returns an explicit `--token` immediately WITHOUT writing it to
`~/.config/beddington/liveview.token`. So a live-view started with `--token X` leaves the
assistant reading a stale/absent token, and FIX 1 alone cannot see it.
Required behaviour: when an explicit token is given and passes the existing
`_LIVE_VIEW_TOKEN_RE` validation, persist it to the same token file (same mkdir + 0o600 +
best-effort OSError handling as the generated-token branch) before returning it. Persisting
must never crash the command if the write fails.

### FIX 3 — notification cooldown started by a notify that soothe suppressed (state.py + pipeline.py)
`CryEventTracker._observe_above` sets `self._last_notification_offset = offset` at the moment
it RETURNS `notify=True` (state.py ~47 and ~67). When soothe is enabled, `run_pipeline`
overwrites `notify` with `soothe_result.notify` (False on activation — soothe defers the
alert), so NO notification is sent but the tracker's cooldown clock has already started. A
new sustained cry within `notification_cooldown_seconds` then gets `notify=False` from the
tracker, `escalation_due=False`, and soothe never re-activates — the second cry gets neither
soothing nor an alert.
Required behaviour: the tracker's re-alert cooldown must reflect notifications ACTUALLY
dispatched, not suppressed pulses. Implement by (a) removing the internal
`self._last_notification_offset = offset` assignments inside `_observe_above` (the tracker
still DECIDES via `_notification_due`, it just stops committing the timestamp itself), and
(b) adding a small public method e.g. `mark_notified(offset)` that sets it; `run_pipeline`
calls `tracker.mark_notified(window.offset_seconds)` only inside the `if notify:` block that
actually calls `notifier.notify(...)` (both the per-window path ~95-104 and the finish path
~181-197). Net effect: non-soothe mode behaves exactly as before (decide → send → mark);
soothe mode no longer poisons the cooldown with a pulse it swallowed.

### FIX 4 — radar never reconnects and serves stale readings as live (sensors.py:212-260)
`Mr60RadarReader._stream` ends in `while True: await asyncio.sleep(3600)` with no disconnect
callback, so a dropped WiFi link never returns/raises into `_run`, the reconnect/backoff loop
(~216-223) never runs again, and `read()` serves the last `self._latest` snapshot forever.
Required behaviour, two parts:
  (4a) STALENESS (must have, must be unit-tested): stamp each `_latest` update with a
  monotonic timestamp; `read()` returns `{}` (treat as no data, NOT a fault) when the newest
  update is older than a staleness window. Use a sensible default (e.g. max(30s, 3x the
  radar/sample cadence)); do not invent new user-facing config unless trivial. This alone
  makes a dead radar distinguishable from a live one.
  (4b) RECONNECT (must have): a dropped connection must cause `_stream` to return so `_run`
  reconnects with backoff; reset `backoff` to 1.0 after a successful connect+subscribe. Use
  whatever the installed aioesphomeapi exposes (a disconnect callback / an asyncio.Event set
  on stop). If the library API makes a clean disconnect signal genuinely unavailable, STOP
  and report it rather than guessing — do not fake it.
Keep `read()` non-blocking and keep the daemon-thread model.

### FIX 5 — systemd ordering cycle (both units)
`deploy/beddington-assistant.service:21` and `deploy/beddington-liveview.service:28` set
`After=default.target` while being `WantedBy=default.target`, forming an ordering cycle a
per-user manager breaks by dropping the service's start job — so after a reboot the service
can silently not start.
Required behaviour: remove `default.target` from the `After=` line of BOTH units (keep
`sound.target` for the assistant; drop the inert `network-online.target` from the live-view
`After=` too, since a per-user manager does not provide it and there is no matching `Wants=`).
Do not change `[Install] WantedBy=`. Units must remain valid.

## Constraints
- Behaviour on all non-safety paths must be identical. No refactors, renames, or reformatting
  beyond what each fix requires.
- Keep every "best-effort, never raise into the monitoring loop" property that exists today
  (alerts, token writes, sensor reads must not crash the loop).
- No new third-party dependencies. No new config keys unless a fix is impossible without one
  (and then only a minimal, defaulted one).
- Python 3.11-3.14. Follow existing code style in each file.

## Acceptance tests
Add focused tests (extend the matching tests/test_*.py) proving each fix; keep the existing
suite green.
1. FIX 1: after constructing the assistant alert path with an empty token, a token written to
   the token file afterwards is used by the next `_fire_cry_alert` (alert reports lan-sent /
   uses the new token). A pure-unit test around the token-refresh is fine — do not require a
   live HTTP server.
2. FIX 2: `_resolve_live_view_token("<valid-token>")` writes that exact token to the token
   file (assert file contents), and a write failure does not raise.
3. FIX 3: a sequence where soothe suppresses the first notify pulse does NOT prevent a later
   in-cooldown sustained cry from producing `escalation_due`/notification; and the non-soothe
   cooldown behaviour is unchanged (add/keep a test that a genuine send starts the cooldown).
4. FIX 4a: a reader whose last update is older than the staleness window returns `{}` from
   `read()`; a fresh update returns the value. Drive time via a monkeypatched/injected clock.
5. FIX 5: a test (or assertion) that neither unit file has `default.target` in its `After=`
   line, and the live-view `After=` no longer names `network-online.target`.

## Non-goals (do NOT touch)
- Any other finding from the review (soothe PID file, volume, assistant command routing,
  liveview slow-loris, config bool coercion, scripts, narrator, etc.). Those are separate
  batches.
- The soothe state machine's own decision logic beyond FIX 3's cooldown bookkeeping.
- The live-view HTTP server internals.
- Reformatting, type-hint sweeps, docstring rewrites, dependency bumps.

## Risk areas (aim the review here)
- FIX 3 changes a state-machine invariant; the danger is over-notifying (spam) or, worse,
  UNDER-notifying (a suppressed cry). Verify both soothe-on and soothe-off paths, and that a
  genuinely delivered notification still enforces the cooldown.
- FIX 1/2: make sure the alert path still never raises into the loop, and the token file
  permissions stay 0o600.
- FIX 4: staleness window must not be so short it drops a live-but-slow radar, nor so long it
  hides a dead one; reconnect must not busy-loop (keep the backoff).
- FIX 5: an invalid unit file would stop the service from starting at all — worse than the
  cycle. Keep the units parseable.
