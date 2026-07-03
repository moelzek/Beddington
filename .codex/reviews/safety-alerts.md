# Review verdict — safety-alerts batch

Branch: `codex/safety-alerts` (base `claude/sad-cannon-7dff4f`)
Implementer: OpenAI Codex (codex-cli 0.142.5, workspace-write). Reviewer: Claude + 6-agent
adversarial workflow + 1 scoped repair pass. Tests: **366 passed** (was 355; +11 new).

Method: Codex implemented the 5 fixes in `.codex/specs/safety-alerts.md` across three
disjoint scoped runs. A 6-reviewer adversarial workflow (per-fix + regression + test-quality)
then attacked the diff, each finding verified by an independent skeptic. One BLOCKING issue
was found (FIX 4b inert against the real library), fixed in exactly one scoped repair pass,
and re-verified.

## Per-fix verdict

| Fix | File(s) | Verdict |
|---|---|---|
| FIX 1 — cry-alert token re-read per alert | cli.py | **CORRECT** — token created after startup is now used; never raises into the loop |
| FIX 2 — persist explicit `--token` | cli.py | **CORRECT** — writes 0o600, write failure swallowed; generated-token path byte-equivalent to before |
| FIX 3 — cooldown reflects dispatched notifications | state.py, pipeline.py | **CORRECT** — both soothe-on and soothe-off traced; no under-notify, no spam |
| FIX 4a — radar staleness window | sensors.py | **CORRECT (1 caveat)** — see NON_BLOCKING below |
| FIX 4b — radar reconnect on disconnect | sensors.py | **FIXED** — was BLOCKING (inert probe); repaired to pass `on_stop` into `connect()`; now tested |
| FIX 5 — systemd ordering cycle removed | both `.service` | **CORRECT** — units still valid; `ExecStartPre=/bin/sleep 25` preserved on live-view |

## BLOCKING (found + fixed)

**FIX 4b reconnect was inert** (sensors.py). The first implementation probed for
`on_stop`/`on_disconnect`/`set_disconnect_callback`/`add_disconnect_callback` as methods on
the `APIClient` instance. Verified against aioesphomeapi v45.5.2: none exist — the disconnect
signal is the `on_stop` **parameter** of `client.connect()`. So the probe returned nothing and
`_stream` awaited an Event that was never set = the original "never reconnects" bug.
Repair: `_stream` now defines `async def on_disconnect(expected)` and calls
`await client.connect(on_stop=on_disconnect, login=True)`; the dead probe helper was removed;
a library-free test (`test_radar_stream_returns_when_aioesphomeapi_on_stop_fires`, fake
`aioesphomeapi` via `sys.modules`) proves `_stream` returns when `on_stop` fires. **Resolved.**

## NON_BLOCKING (ship, but know these — aim your Pi test here)

1. **FIX 4a can false-blank a totally static radar scene.** `_latest_updated_at` only advances
   when `on_state` fires. In a presence-only config (distance/target-count/vitals all off), if
   ESPHome pushes state only on change and the scene is perfectly still for >30s, `read()`
   returns `{}` — a live radar reads as "unavailable." Blast radius is limited: the radar feeds
   only environment context, **not** the audio cry-alert trigger, so it can never suppress an
   alert. On the Pi, watch whether a still/sleeping baby makes presence drop out; if so, raise
   the staleness window or key freshness off connection-state instead of last-data-time.
2. **FIX 3 state-level unit tests don't fail if the fix is reverted** (the pipeline
   soothe-suppression test is the real guard, and it does hold). Cosmetic test-robustness gap,
   not a correctness risk.

## Considered, deliberately not flagged
- Explicit `--token` now overwrites a previously-persisted generated token — that is the
  intended FIX 2 behavior.
- One extra `open()` per cry trigger (token re-read) — cry triggers are rare; negligible.
- `_reset()` still doesn't clear `_last_notification_offset` — pre-existing, intentional
  (cooldown persists across episodes by design).
- Almost-empty `[Unit]` section on live-view after dropping `After=` — valid systemd.

## Residual risk
Behavior-changing fixes on the alert/soothe/sensor paths. Verify on real Pi hardware:
(a) a cry with the assistant started before live-view still reaches the phone; (b) two cries
inside the cooldown both alert/soothe under soothe-on; (c) pull the radar's power and confirm
it reads unavailable then auto-recovers on reconnect; (d) reboot and confirm both services
start. All five are CONFIRMED-high review findings; none were covered by tests before this batch.
