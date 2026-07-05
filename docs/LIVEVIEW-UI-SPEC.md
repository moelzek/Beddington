# Live View UI Specification: Parent-First Dashboard

Status: implementable product/UI specification.  
Source plan: `LIVEVIEW-UI-SPEC-PLAN.md` v2, signed off 2026-07-05.  
Scope: phone and desktop web redesign for the Beddington live-view dashboard.  
Deliverable: document only; no UI implementation in this task.

## 0. Overview & Principles

The redesigned live view turns the current engineering dashboard into a parent-first screen that answers: "Do I need to do anything right now?" It must work on a phone at night, on a desktop during setup, and on a Raspberry Pi-served single-file web page with no external assets.

The UI is built around five layers: State, Action, Evidence, Memory, and Debug. The first screen shows State and Action first, Evidence one tap away, Memory in its own navigation item, and Debug behind Settings.

Hard product constraints:

- Display only observations and labelled best guesses. Do not display inferred baby-state labels; the scoped banned terms are in Section 8.
- Never use reassuring health/safety language about the baby. No SIDS, diagnosis, medical certainty, or implication that adult checking is unnecessary.
- Vitals are "rough radar estimate" data and appear only when the radar has a genuine breathing lock.
- Presence must distinguish no reading from no one detected.
- Cry scores are uncalibrated model scores, never probabilities.
- Privacy badge copy is exactly: "LAN only · no cloud · no recording · no audio streaming".
- Implementation envelope: vanilla JS, single HTML response, no CDN, polling, canvas charts, and no more than 6 concurrent MJPEG streams.

### Product Principles

| # | Principle | Testable requirement |
|---|---|---|
| 1 | Answer the parent question first | The first visible Home content is `StateHero` plus `ActionCard`, before charts or debug data. |
| 2 | Observe, do not infer | All state labels describe sensor observations; inferred state-machine keys stay internal. |
| 3 | One primary action | Exactly one primary action is attached to the active state; secondary room actions are visually separate. |
| 4 | Evidence is close | Every state, action, and alert has tap-through evidence chips with source, age, and confidence basis. |
| 5 | Missing data is explicit | Missing presence, stale readings, camera outage, and no history each have distinct copy and UI states. |
| 6 | Night use is first-class | Night mode uses dim colors, large text, no white flashes, and one-hand reachable controls. |
| 7 | Memory is factual | Night and pattern cards cite persisted sensor history and label derived patterns "best guess". |
| 8 | Privacy is visible | The exact privacy badge appears on Home and in Settings; token/LAN caveats are one tap away. |
| 9 | Accessible by default | WCAG 2.2 AA contrast, 44 px touch targets, keyboard support, `aria-live`, and reduced motion are required. |
| 10 | Pi-friendly and local | No external fonts/libraries/CDNs; bounded polling, payloads, canvas work, and MJPEG viewer count. |

### Deliverable Trace

| Plan deliverable | Covered in this spec |
|---|---|
| Information architecture | Section 1 |
| Mobile layout | Section 5 |
| Desktop layout | Section 6 |
| Component list | Section 7 |
| State hierarchy | Section 2 |
| Alert hierarchy | Section 4 |
| UX copy catalogue | Section 8 |
| Accessibility requirements | Section 10 |
| Acceptance criteria and language test plan | Section 13 |

### Data Source Legend

| Source | Status | Real source or proposed contract | Notes |
|---|---|---|---|
| `/` | Real | `src/beddington/liveview.py::_make_handler` | Token-gated HTML page. |
| `/stream.mjpg` | Real | `src/beddington/liveview.py`, `FrameBroker`, `_ModeBroker` | MJPEG stream; cap 6 viewers; 503 over cap. |
| `/readings.json` | Real | `src/beddington/cli.py::_dashboard_fields`, `_SensorSampler.latest()` | Display strings for room readings, presence, vitals, `mode`, `mode_auto`. |
| `/history.json` | Real | `SensorStore.series()` or `liveview.history_series(_SensorSampler.history())` | Per-sensor `{label, unit, bool, points}`. Store path downsampled to 400 points per sensor. |
| `/digest.json` | Real when store exists | `cli.py::_summarise_store_night`, `night_digest.summarise_night()` | Returns `{text}` deterministic night summary. |
| `/soothe.json`, `POST /soothe`, `POST /autosoothe` | Real when Soothe exists | `liveview.py::_make_handler`, `_DashboardSoothe` from `cli.py` | Local nursery sound control. No audio streaming to browser. |
| `POST /mode` | Real when sensors exist | `_SensorSampler.set_override()` and `day_night_mode()` | Day/night/auto control. |
| `/alerts.json`, `POST /alert` | Real, single-alert v1 | `liveview.py::_AlertState` | Single alert, TTL 45 s, `seq`, `score`, `age_seconds`. |
| SQLite `readings` | Real | `src/beddington/sensor_store.py` | `(ts, key, value)` numeric derived readings. |
| SQLite `soothe_outcomes` | Real | `src/beddington/sensor_store.py` | `(ts, sound_name, success, context)` local soothe outcome history. |
| SQLite `cry_episodes` | Real | `src/beddington/sensor_store.py` | `(started_ts, ended_ts, duration_seconds)`. |
| `night_aggregates()` | Real | `src/beddington/sensor_store.py` | Stir-hour counts and per-sound soothe tallies over N nights. |
| Assistant room labels | Real | `src/beddington/assistant.py` | Temperature comfortable 16-20 C; humidity 40-60%; pressure label can be "normal" for room pressure. |
| `/state.json` | **PROPOSED** | Formal schema in Section 2 | Server-side state derivation. Client derivation from display strings is rejected. |
| Multi-alert `/alerts.json` | **PROPOSED** | Formal schema in Section 4 | Replaces single `_AlertState` for T2/T3 and server-side ack/snooze. |
| `[liveview.state]` | **PROPOSED** | TOML schema in Section 2 | New config block; not present in current config. |
| Caregiver identity | **FUTURE** | Missing signal: trusted caregiver identity or person classification | Not derivable from current sensors or camera stream. |

## 1. IA & Navigation Map

### Five-Layer IA

| Layer | Parent question | Primary UI | Data source |
|---|---|---|---|
| State | What is happening right now? | `StateHero` on Home | **PROPOSED** `/state.json`; evidence from real `/readings.json`, `/alerts.json`, `/history.json`, `/stream.mjpg` health. |
| Action | Do I need to do anything? | `ActionCard` plus optional `RoomActionCard` | **PROPOSED** `/state.json.action`; room action from real assistant temperature bands in `assistant._temp_label()`. |
| Evidence | Why does it say that? | `EvidenceStrip`, `EvidenceChartSheet` | Real `/readings.json`, `/history.json`, SQLite `readings`; **PROPOSED** evidence array in `/state.json`. |
| Memory | What happened tonight / recently? | Memory tab cards | Real `/digest.json`, SQLite `cry_episodes`, `soothe_outcomes`, `night_aggregates()`; 7-night compare is **PROPOSED**. |
| Debug | What are raw sensors doing? | Settings -> Engineering drawer | Real `/history.json`, `/readings.json`, `/alerts.json`, stream status; logs are not exposed today and are **PROPOSED** if shown. |

### Phone Navigation

Bottom navigation:

1. Home: current state, action, camera thumbnail, evidence strip.
2. Live: full-screen camera with dim overlays and mode control.
3. Memory: tonight summary, last-night card, patterns.
4. Settings: privacy, notifications, day/night override, Soothe defaults, Engineering entry.

No tabs are used for State, Action, or Evidence on phone. Sensor charts open from evidence chips as bottom sheets.

### Desktop Navigation

Desktop has no bottom navigation. It uses a persistent 3-column dashboard:

- Left: state, action, privacy, settings shortcuts.
- Center: large camera and evidence strip.
- Right: tonight timeline and memory cards.
- Bottom drawer: Engineering debug graphs, collapsed by default.

No information is hover-only. Hover can reveal tooltips, but every tooltip must also be reachable by focus or tap.

## 2. State Hierarchy

The active state is computed server-side by **PROPOSED** `GET /state.json`. The client must render state, action, confidence, and evidence from that response. It must not parse `/readings.json` display strings to derive state.

Exactly one active state is selected by top-down precedence. Higher-precedence states can interrupt lower-precedence dwell timers.

### State Table

| Prec. | Internal key | Display label | Derived from | Source status |
|---|---|---|---|---|
| 1 | `crying` | "Crying detected — {m} min" | Active cry alert or sustained cry score | Real alert source: `POST /alert`, `/alerts.json`, `cli.py::_notify_live_view_cry_alert`; state output **PROPOSED** `/state.json`. |
| 2 | `sensor_unreliable` | "Sensors need attention" | Reading staleness, camera stream health, radar clutter | **PROPOSED** health contract; raw readings and stream exist. |
| 3 | `not_detected` | "No one detected" or "No presence reading" | `person_present` false vs missing; `radar_person_present()` corroboration rules | Real raw signal in `/readings.json` source snapshot and SQLite `readings`; missing/no-one split required in **PROPOSED** `/state.json`. |
| 4 | `caregiver_present` | "Large movement — someone's in the room" | Caregiver identity | **FUTURE**; missing signal: trusted caregiver identity or person classification. V1 may only display large/multiple movement as evidence, not identity. |
| 5 | `wiggling` | "Moving in the last {n} min" | Server-counted `motion_detected` transitions | Real `motion_detected` readings; transition count must be server-side, not from downsampled client history. |
| 6 | `sleeping` | "Still for {n} min · best guess" | Presence plus no motion for threshold | Real presence/motion signals; state output **PROPOSED** `/state.json`. Internal key only. |
| 7 | `calm` | "Quiet, occasional movement · best guess" | Presence, sparse motion, no active cry alert | Real signals; absence of alert is not proof of no crying. Internal key only. |
| - | `uncertain` | "Not sure right now — check the camera" | Fallback | Real or partial signals; state output **PROPOSED** `/state.json`. |

### State Diagram

```text
Incoming samples
  |
  +-- Cry alert active? ---------------------------> crying
  |
  +-- Required sensor/camera health failed? -------> sensor_unreliable
  |
  +-- No presence reading? ------------------------> not_detected
  |                                                  label: "No presence reading"
  |
  +-- Presence false or uncorroborated? -----------> not_detected
  |                                                  label: "No one detected"
  |
  +-- FUTURE caregiver identity? ------------------> caregiver_present
  |
  +-- Motion transition in window? ----------------> wiggling
  |
  +-- Presence true and still threshold met? ------> sleeping
  |
  +-- Presence true and sparse movement? ----------> calm
  |
  +-- Otherwise -----------------------------------> uncertain
```

### State Inputs

| Input | Meaning | Source | Required handling |
|---|---|---|---|
| Cry alert active | Sustained crying detector raised alert | Real `/alerts.json.active`; `POST /alert`; `cli.py::_notify_live_view_cry_alert()` | Display "Crying detected"; score is an uncalibrated score, not a probability. |
| Cry score | YAMNet model score | Real alert `score` field today | May appear only as "cry score {score}". No percent, probability, or certainty wording. |
| Presence reading | Radar `person_present` plus corroboration | Real `assistant.radar_person_present()` and `_dashboard_fields()` | `None` means no presence reading. `False` means no one detected. |
| Motion transitions | Off-to-on movement transitions | Real SQLite `readings.key='motion_detected'` or sampler history | Count server-side from raw samples; do not count from downsampled `/history.json` client points. |
| Room temperature | Room comfort action | Real `/readings.json.temperature`; `assistant._temp_label()` | 16-20 C is comfortable room range. Below/above can trigger `adjust_room`. |
| Radar breathing | Rough vitals estimate | Real `/readings.json.vitals` only when `radar_respiratory_rate` exists | Hide without breathing lock. Label as rough radar estimate. |
| Camera stream health | Frame freshness and stream errors | **PROPOSED** health field in `/state.json` | Needed for `sensor_unreliable` and camera-down T2 alert. |
| Reading staleness | Last sample age per signal | **PROPOSED** health field in `/state.json` | Needed for stale/offline handling. |

### Thresholds, Hysteresis, Dwell

These defaults live in **PROPOSED** `[liveview.state]` TOML. They are product defaults, not current repo config.

| Rule | Default | Unit | Applies to | Behavior |
|---|---:|---|---|---|
| `max_reading_age_s` | 12 | seconds | `sensor_unreliable`, confidence | A required reading older than this is stale. |
| `max_camera_frame_age_s` | 8 | seconds | `sensor_unreliable`, camera T2 | No frame within this age means camera health failed. |
| `max_radar_age_s` | 12 | seconds | presence states | Presence/motion older than this cannot produce high confidence. |
| `health_bad_checks_to_enter` | 2 | checks | `sensor_unreliable` | Enter only after two consecutive bad health checks. |
| `health_recovered_checks_to_exit` | 3 | checks | `sensor_unreliable` | Exit only after three consecutive recovered checks. |
| `state_min_dwell_s` | 20 | seconds | lower-precedence states | Prevents flapping between `wiggling`, `sleeping`, `calm`, and `uncertain`. |
| `cry_clear_grace_s` | 30 | seconds | `crying` | Keep `crying` briefly after alert clears unless a higher health issue appears. |
| `motion_window_s` | 300 | seconds | `wiggling` | If movement occurred within this window, label with minutes. |
| `motion_active_min_s` | 3 | seconds | `wiggling` | Ignore one-sample spikes shorter than this. |
| `wiggling_release_s` | 120 | seconds | `wiggling` | Remain in `wiggling` until no movement for this release window. |
| `still_min_s` | 1200 | seconds | `sleeping` key | Presence plus no motion for 20 minutes enters "Still..." label. |
| `still_exit_motion_s` | 3 | seconds | `sleeping` key | Any confirmed motion exits still state. |
| `quiet_window_s` | 900 | seconds | `calm` key | Sparse movement window. |
| `quiet_max_motion_transitions` | 2 | count | `calm` key | More transitions routes to `wiggling`. |
| `presence_false_dwell_s` | 10 | seconds | `not_detected` | Requires repeated false/no-target reading before "No one detected". |
| `room_cold_below_c` | 16 | C | room action | Below this surfaces `adjust_room`. |
| `room_warm_above_c` | 20 | C | room action | Above this surfaces `adjust_room`. |
| `room_temp_hysteresis_c` | 0.5 | C | room action | Room action clears only after returning inside range by 0.5 C. |

High-precedence overrides:

- `crying` interrupts every lower state immediately.
- `sensor_unreliable` interrupts every lower state after `health_bad_checks_to_enter`.
- `not_detected` interrupts movement/still/quiet states when presence is false or missing.

### Missing-Data Behavior

| Missing or partial data | State output | Confidence | Evidence copy |
|---|---|---|---|
| `person_present` missing | `not_detected` with label "No presence reading" unless broader health issue wins | Low | "presence · no reading · {age}s" |
| `person_present` false | `not_detected` with label "No one detected" | Medium/high based on freshness | "presence · no one detected · {age}s" |
| Bare `person_present=true` without target or breathing lock | `not_detected` or `uncertain` based on implementation evidence | Low/medium | "radar flag not corroborated" |
| Motion missing but presence fresh | `sensor_unreliable` if stale threshold crossed; otherwise `uncertain` | Low | "motion · no fresh reading" |
| Camera down but sensors fresh | `sensor_unreliable` | Medium | "camera · no frame for {n}s" |
| Store unavailable | State still works from live sampler; Memory shows no-store empty state | State confidence unaffected unless history-dependent | "history · not stored for this session" |
| `/state.json` unavailable | Client shows `SessionError` and falls back to camera-only view | Low | "state service unavailable" |

### Confidence Definition

Confidence is not duration and is not cry probability. It is a band explaining the quality of the contributing signals.

| Band | Rule | Example basis |
|---|---|---|
| High | All required contributing signals are fresh; presence is corroborated by target count/distance or breathing lock; motion was counted server-side from raw samples; camera health is current when used. | "fresh presence + no motion transitions + camera frame age 1s" |
| Medium | One non-critical signal is stale or uncorroborated, but the state still has a direct current signal. | "presence false fresh; motion last updated 18s ago" |
| Low | Fallback, missing presence, missing motion, or state relies on partial data. | "presence missing; camera visible" |

### Worked Precedence Examples

| Example | Inputs | Result |
|---|---|---|
| Cry plus stillness | Active T1 cry alert, presence true, no motion 45 min | `crying`, "Crying detected — {m} min"; cry wins over stillness. |
| Camera outage plus quiet room | Camera frame age 20 s, room readings fresh, no active cry | `sensor_unreliable`, "Sensors need attention"; camera health wins over quiet state. |
| No presence reading | `person_present=None`, motion absent, camera visible | `not_detected`, "No presence reading"; do not display "No one detected". |
| Movement after long still period | Presence true, no motion 40 min, then 2 motion transitions in 5 min | `wiggling`, "Moving in the last 5 min"; movement exits still state after `still_exit_motion_s`. |
| Warm room while quiet | Presence true, sparse movement, temp 23 C | State label "Quiet, occasional movement · best guess"; primary action from state plus separate room action "Adjust room". |

### PROPOSED `/state.json` Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://beddington.local/schemas/liveview-state.schema.json",
  "title": "Beddington Live View State",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "generated_ts",
    "state",
    "label",
    "confidence",
    "since_ts",
    "evidence",
    "action",
    "mode",
    "health",
    "links"
  ],
  "properties": {
    "schema_version": { "const": 1 },
    "generated_ts": { "type": "number", "description": "Unix seconds" },
    "state": {
      "type": "string",
      "enum": [
        "crying",
        "sensor_unreliable",
        "not_detected",
        "caregiver_present",
        "wiggling",
        "sleeping",
        "calm",
        "uncertain"
      ]
    },
    "label": {
      "type": "string",
      "description": "Observational display label. Must pass Section 8 language policy."
    },
    "confidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["band", "basis"],
      "properties": {
        "band": { "type": "string", "enum": ["high", "medium", "low"] },
        "basis": { "type": "string" }
      }
    },
    "since_ts": {
      "type": ["number", "null"],
      "description": "Unix seconds when this state began; null when unknown."
    },
    "display_duration_s": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Optional precomputed duration for labels."
    },
    "evidence": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/evidence" }
    },
    "action": { "$ref": "#/$defs/action" },
    "room_action": {
      "anyOf": [{ "$ref": "#/$defs/action" }, { "type": "null" }],
      "description": "Optional separate room comfort action."
    },
    "mode": {
      "type": "object",
      "additionalProperties": false,
      "required": ["value", "auto", "source"],
      "properties": {
        "value": { "type": "string", "enum": ["day", "night"] },
        "auto": { "type": "boolean" },
        "source": { "type": "string", "const": "/readings.json.mode" }
      }
    },
    "health": {
      "type": "object",
      "additionalProperties": false,
      "required": ["camera", "readings", "radar", "history"],
      "properties": {
        "camera": { "$ref": "#/$defs/health_item" },
        "readings": { "$ref": "#/$defs/health_item" },
        "radar": { "$ref": "#/$defs/health_item" },
        "history": { "$ref": "#/$defs/health_item" }
      }
    },
    "privacy_badge": {
      "type": "string",
      "const": "LAN only · no cloud · no recording · no audio streaming"
    },
    "links": {
      "type": "object",
      "additionalProperties": false,
      "required": ["stream", "readings", "history", "alerts"],
      "properties": {
        "stream": { "type": "string" },
        "readings": { "type": "string" },
        "history": { "type": ["string", "null"] },
        "alerts": { "type": "string" },
        "soothe": { "type": ["string", "null"] },
        "digest": { "type": ["string", "null"] }
      }
    }
  },
  "$defs": {
    "evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["signal", "label", "value", "source", "age_s", "weight", "status"],
      "properties": {
        "signal": { "type": "string" },
        "label": { "type": "string" },
        "value": {
          "type": ["string", "number", "boolean", "null"],
          "description": "Raw or formatted value; null means no reading."
        },
        "unit": { "type": ["string", "null"] },
        "source": {
          "type": "string",
          "description": "Endpoint, SQLite table, module, PROPOSED field, or FUTURE signal."
        },
        "age_s": { "type": ["number", "null"], "minimum": 0 },
        "weight": { "type": "number", "minimum": 0, "maximum": 1 },
        "status": {
          "type": "string",
          "enum": ["fresh", "stale", "missing", "uncorroborated", "future"]
        }
      }
    },
    "action": {
      "type": "object",
      "additionalProperties": false,
      "required": ["key", "label", "detail", "evidence_signals"],
      "properties": {
        "key": {
          "type": "string",
          "enum": [
            "none",
            "check_room",
            "comfort_now",
            "reposition_device",
            "check_power",
            "adjust_room",
            "check_camera"
          ]
        },
        "label": { "type": "string" },
        "detail": { "type": "string" },
        "target_href": { "type": ["string", "null"] },
        "evidence_signals": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    },
    "health_item": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "age_s", "source"],
      "properties": {
        "status": { "type": "string", "enum": ["fresh", "stale", "missing", "error"] },
        "age_s": { "type": ["number", "null"], "minimum": 0 },
        "source": { "type": "string" },
        "detail": { "type": "string" }
      }
    }
  }
}
```

### PROPOSED `[liveview.state]` TOML Schema

```toml
[liveview.state]
# Freshness and health
max_reading_age_s = 12.0
max_camera_frame_age_s = 8.0
max_radar_age_s = 12.0
health_bad_checks_to_enter = 2
health_recovered_checks_to_exit = 3

# State dwell and release
state_min_dwell_s = 20.0
cry_clear_grace_s = 30.0
presence_false_dwell_s = 10.0

# Motion and stillness
motion_window_s = 300.0
motion_active_min_s = 3.0
wiggling_release_s = 120.0
still_min_s = 1200.0
still_exit_motion_s = 3.0
quiet_window_s = 900.0
quiet_max_motion_transitions = 2

# Room comfort action, aligned with assistant._temp_label()
room_cold_below_c = 16.0
room_warm_above_c = 20.0
room_temp_hysteresis_c = 0.5

# Payload and evidence limits
max_evidence_items = 8
max_alerts_returned = 20
```

Validation rules:

- Durations must be non-negative.
- `health_bad_checks_to_enter`, `health_recovered_checks_to_exit`, and `quiet_max_motion_transitions` must be integers >= 1, except `quiet_max_motion_transitions` may be 0.
- `room_cold_below_c` must be less than `room_warm_above_c`.
- `room_temp_hysteresis_c` must be >= 0 and <= 2.

## 3. Action Layer

Each state returns exactly one primary action in `/state.json.action`. Room comfort can surface as one separate `room_action` because it comes from room sensors and may coexist with any baby-observation state.

Actions are suggestions. The UI must phrase them as suggested next steps and always show the evidence that caused them.

### Primary Action Map

| State key | Primary action key | Display label | Detail copy | Source |
|---|---|---|---|---|
| `crying` | `comfort_now` | "Comfort now" | "Soothe is available on this device." | Real `/alerts.json`; real Soothe endpoints when wired; `target_href` is null if Soothe is absent. |
| `sensor_unreliable` | `reposition_device` or `check_power` | "Check the device" | "One or more readings need attention." | **PROPOSED** health fields in `/state.json`. |
| `not_detected` with no reading | `check_room` | "Check the room" | "There is no presence reading right now." | Real presence raw signal; missing split **PROPOSED** in `/state.json`. |
| `not_detected` with false reading | `check_camera` | "Check the camera" | "Radar does not detect anyone." | Real `person_present=false`/corroboration; camera source real. |
| `caregiver_present` | `none` | "No suggested action" | "Large movement is visible in the room." | **FUTURE** caregiver identity; v1 movement-only evidence must not identify the person. |
| `wiggling` | `check_camera` | "Check the camera" | "Movement was detected recently." | Real `motion_detected`; server transition count **PROPOSED**. |
| `sleeping` | `none` | "No suggested action" | "Stillness is a best guess from the available readings." | Real presence/motion; state output **PROPOSED**. |
| `calm` | `none` | "No suggested action" | "Quiet movement pattern is a best guess from the available readings." | Real presence/motion and no active alert; state output **PROPOSED**. |
| `uncertain` | `check_camera` | "Check the camera" | "The readings do not point to one clear state." | **PROPOSED** `/state.json`. |

### Room Action

Room comfort actions are separate from the baby-observation state.

| Trigger | Action key | Label | Detail | Source |
|---|---|---|---|---|
| Temperature < 16 C | `adjust_room` | "Adjust room" | "Room temperature is {t}°C · a bit cool." | Real `/readings.json.temperature`; `assistant._temp_label()`. |
| Temperature > 20 C | `adjust_room` | "Adjust room" | "Room temperature is {t}°C · a bit warm." | Real `/readings.json.temperature`; `assistant._temp_label()`. |
| Temperature back inside range with hysteresis | no `room_action` | - | - | **PROPOSED** `[liveview.state].room_temp_hysteresis_c`. |

If the baby-observation state has `none` but the room is too warm/cool, Home shows:

```text
StateHero: "Quiet, occasional movement · best guess"
ActionCard: "No suggested action"
RoomActionCard: "Adjust room"
```

## 4. Alert Hierarchy

The current repo supports one active alert via `_AlertState`. T2/T3 alerts require a **PROPOSED** multi-alert server contract.

### Alert Tier Matrix

| Tier | Severity | Triggers | UI | Sound/notification | Source |
|---|---|---|---|---|---|
| T1 Urgent | Red | Sustained crying | Sticky banner plus alert tray item until ack or TTL | Beep after Web-Audio unlock; browser notification if granted | Real `_AlertState`, `/alert`, `/alerts.json`; multi-alert fields **PROPOSED**. |
| T2 Attention | Amber | Room too warm/cool, sensor stale/offline, camera down, device restarted | Amber alert card, not full-screen | Browser notification; no beep by default, including at night | **PROPOSED** multi-alert contract; room temperature source real. |
| T3 Info | Inline | Soothe started/stopped, night summary ready, day/night switch | Quiet inline item or timeline marker | No notification | **PROPOSED** multi-alert contract; Soothe and mode sources real. |

### Lifecycle

| Step | Required behavior |
|---|---|
| Raise | Server creates alert with `id`, `seq`, tier, type, evidence, confidence, action, and timestamps. Current T1 is raised by `POST /alert`. |
| Notify once | Each browser stores `last_notified_seq` locally and fires sound/Notification only once per new `seq`. |
| Visual display | T1 uses `aria-live="assertive"` and remains visible until ack or TTL. T2 uses `aria-live="polite"`. T3 stays inline. |
| Ack | Ack is server-side per alert. Ack removes the sticky banner on all viewers and marks the tray item acknowledged. |
| Snooze | T1 snooze mutes repeat sound/notification only; visual remains while active. T2 snooze hides the card until `snoozed_until_ts` unless a new `seq` is raised. T3 has no snooze. |
| Repeat/cooldown | T1 repeat uses existing cry tracker cooldown and alert `seq`. T2 repeat cooldown defaults to 10 min **PROPOSED**. T3 repeats only when the event changes. |
| TTL/self-heal | Current T1 TTL is 45 s from `_ALERT_TTL_SECONDS`; proposed contract uses `expires_ts`. Alerts disappear after recovery/expiry unless retained in Memory. |
| Multi-viewer sync | Server-side ack/snooze state is returned to all viewers on next poll. Web-Audio unlock and Notification permission remain per browser. |
| Notification denied | UI shows "Notifications are blocked in this browser. Alerts will stay on this screen." It must continue in-page alerts and document-title badge updates. |
| Web-Audio locked | UI shows "Tap to enable sound alerts." T1 visual alert still appears even before unlock. |

### Alert Copy

| Alert type | Tier | Title | Message | Action |
|---|---|---|---|---|
| `cry_sustained` | T1 | "Crying detected" | "Sustained crying; cry score {score}." | "Comfort now" when Soothe exists, otherwise "Check the room". |
| `room_warm` | T2 | "Room a bit warm" | "Temperature {t}°C; usual room range 16-20°C." | "Adjust room". |
| `room_cool` | T2 | "Room a bit cool" | "Temperature {t}°C; usual room range 16-20°C." | "Adjust room". |
| `sensor_stale` | T2 | "Sensor readings stale" | "No fresh {signal} reading for {n}s." | "Check the device". |
| `camera_down` | T2 | "Camera not reachable" | "No camera frame for {n}s." | "Check the camera". |
| `device_restarted` | T2 | "Device restarted" | "Readings resumed after a restart." | "Review readings". |
| `soothe_started` | T3 | "Soothe started" | "Playing {sound} in the nursery." | "Open Soothe". |
| `soothe_stopped` | T3 | "Soothe stopped" | "Nursery sound stopped." | "Open Soothe". |
| `digest_ready` | T3 | "Night summary ready" | "New room summary available." | "Open Memory". |
| `mode_changed` | T3 | "Night eye active" or "Day eye active" | "Camera mode changed from room light." | "Open Live". |

### PROPOSED Multi-Alert JSON Schema

This schema replaces the current single-alert response while preserving enough fields to render current T1 behavior.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://beddington.local/schemas/liveview-alerts.schema.json",
  "title": "Beddington Live View Alerts",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "generated_ts", "alerts", "server_seq"],
  "properties": {
    "schema_version": { "const": 2 },
    "generated_ts": { "type": "number" },
    "server_seq": { "type": "integer", "minimum": 0 },
    "alerts": {
      "type": "array",
      "maxItems": 20,
      "items": { "$ref": "#/$defs/alert" }
    }
  },
  "$defs": {
    "alert": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "seq",
        "tier",
        "type",
        "title",
        "message",
        "state",
        "raised_ts",
        "updated_ts",
        "expires_ts",
        "confidence",
        "evidence",
        "action",
        "notification"
      ],
      "properties": {
        "id": { "type": "string" },
        "seq": { "type": "integer", "minimum": 1 },
        "tier": { "type": "string", "enum": ["T1", "T2", "T3"] },
        "type": {
          "type": "string",
          "enum": [
            "cry_sustained",
            "room_warm",
            "room_cool",
            "sensor_stale",
            "camera_down",
            "device_restarted",
            "soothe_started",
            "soothe_stopped",
            "digest_ready",
            "mode_changed"
          ]
        },
        "title": { "type": "string" },
        "message": { "type": "string" },
        "state": {
          "type": "string",
          "enum": ["active", "acknowledged", "snoozed", "expired", "cleared"]
        },
        "raised_ts": { "type": "number" },
        "updated_ts": { "type": "number" },
        "expires_ts": { "type": ["number", "null"] },
        "acknowledged_ts": { "type": ["number", "null"] },
        "acknowledged_by": { "type": ["string", "null"] },
        "snoozed_until_ts": { "type": ["number", "null"] },
        "repeat_after_s": { "type": ["number", "null"], "minimum": 0 },
        "confidence": {
          "type": "object",
          "additionalProperties": false,
          "required": ["band", "basis"],
          "properties": {
            "band": { "type": "string", "enum": ["high", "medium", "low"] },
            "basis": { "type": "string" }
          }
        },
        "evidence": {
          "type": "array",
          "items": { "$ref": "liveview-state.schema.json#/$defs/evidence" }
        },
        "action": { "$ref": "liveview-state.schema.json#/$defs/action" },
        "notification": {
          "type": "object",
          "additionalProperties": false,
          "required": ["browser", "sound"],
          "properties": {
            "browser": { "type": "boolean" },
            "sound": { "type": "boolean" },
            "sound_requires_unlock": { "type": "boolean" }
          }
        }
      }
    }
  }
}
```

Companion **PROPOSED** endpoints:

| Endpoint | Method | Body/query | Result |
|---|---|---|---|
| `/alerts.json` | GET | token query | Multi-alert schema above. |
| `/alerts/{id}/ack` | POST | token query, optional `device_id` | Marks alert acknowledged server-side. |
| `/alerts/{id}/snooze` | POST | token query, `seconds` | Sets `snoozed_until_ts` per lifecycle rules. |
| `/alerts/{id}/clear` | POST | token query | Clears recoverable T2/T3 alerts; T1 clear remains tied to cry alert recovery. |

## 5. Mobile Layout

Phone is portrait-first. The Home screen must be useful without opening any tab, chart, or settings panel.

### Home Screen, Portrait

```text
+------------------------------------------------+
| Status bar                                     |
| Beddington                         Night / Day |
| LAN only · no cloud · no recording             |
| · no audio streaming                           |
|                                                |
| +--------------------------------------------+ |
| | StateHero                                  | |
| | "Still for 40 min · best guess"            | |
| | Confidence: medium                         | |
| | Since 02:14                                | |
| +--------------------------------------------+ |
|                                                |
| +--------------------------------------------+ |
| | ActionCard                                 | |
| | No suggested action                         | |
| | Why: presence + no recent movement          | |
| +--------------------------------------------+ |
|                                                |
| +--------------------------------------------+ |
| | CameraTile                                 | |
| | [dim live thumbnail, tap for full screen]   | |
| +--------------------------------------------+ |
|                                                |
| EvidenceStrip                                 |
| [19°C] [48%] [dark] [presence] [radar est.]   |
|                                                |
| +--------------------------------------------+ |
| | Optional RoomActionCard                     | |
| | Adjust room                                | |
| +--------------------------------------------+ |
|                                                |
| Home        Live        Memory      Settings  |
+------------------------------------------------+
```

Annotations:

- `StateHero` uses `/state.json.label`, confidence, and `since_ts`.
- Privacy badge wraps to two lines on narrow screens but must stay above State.
- `CameraTile` uses `/stream.mjpg`; if stream returns 503, it shows the cap message.
- Evidence chips open `EvidenceChartSheet`; chips cite real source and age.
- `RoomActionCard` appears only when `/state.json.room_action` exists.

### T1 Alert Overlay

```text
+------------------------------------------------+
| ALERT: Crying detected                         |
| Sustained crying; cry score 0.87.              |
| [Comfort now] [Mute sound 5 min] [Acknowledge] |
+------------------------------------------------+
| Home content remains visible below             |
+------------------------------------------------+
```

T1 overlay is sticky, red, and `aria-live="assertive"`. Acknowledge is server-side in the **PROPOSED** multi-alert contract; current single-alert v1 falls back to TTL.

### Live Screen

```text
+------------------------------------------------+
| < Home                              Night eye  |
|                                                |
|                 CameraFullScreen               |
|             [MJPEG stream, dim at night]       |
|                                                |
| +--------------------------------------------+ |
| | overlay: 19°C · dark · No presence reading | |
| +--------------------------------------------+ |
|                                                |
| [Rotate] [Day/Night/Auto] [Evidence]           |
+------------------------------------------------+
```

Live screen rules:

- Night camera frames are dimmed by CSS until tapped; no white flash during load.
- Mode control uses real `POST /mode`; current mode uses `/readings.json.mode`.
- Overlay copy must not cover the center of the camera. It docks to bottom and can collapse.

### Evidence Bottom Sheet

```text
+------------------------------------------------+
| Evidence: motion                               |
| Source: SQLite readings.motion_detected        |
| Last reading: 7s ago                           |
|                                                |
| [canvas chart, current window]                 |
|                                                |
| Basis                                          |
| - no motion transitions in 40 min              |
| - presence reading fresh                       |
|                                                |
| [Close]                                       |
+------------------------------------------------+
```

Chart data comes from `/history.json`. Transition counts must come from `/state.json.evidence`, not from downsampled chart points.

### Memory Screen

```text
+------------------------------------------------+
| Memory                                         |
| Tonight                                        |
| +--------------------------------------------+ |
| | "Here's the room so far:"                  | |
| | deterministic digest text from /digest.json| |
| +--------------------------------------------+ |
|                                                |
| Cry episodes: {count}                          |
| What helped                                    |
| [rain 2/3] [waves 1/2]                         |
| Usually stirs                                  |
| "~2am · best guess"                            |
|                                                |
| Home        Live        Memory      Settings  |
+------------------------------------------------+
```

Sources:

- Digest text: real `/digest.json` when store exists.
- Cry count: real SQLite `cry_episodes`; count endpoint is **PROPOSED** unless included in `/state.json` or Memory contract.
- What helped: real SQLite `soothe_outcomes` via `night_aggregates()`.
- 7-night comparison: **PROPOSED** aggregate over `night_aggregates()`.

### Settings and Engineering

```text
+------------------------------------------------+
| Settings                                       |
| Privacy                                        |
| LAN only · no cloud · no recording             |
| · no audio streaming                           |
| [Open privacy details]                         |
|                                                |
| Alerts                                         |
| [Enable sound alerts] [Browser notifications]  |
|                                                |
| Camera mode                                    |
| [Auto] [Day] [Night]                           |
|                                                |
| Engineering                                    |
| [Open raw readings and graphs]                 |
+------------------------------------------------+
```

Engineering opens a labelled debug drawer. It is not part of the default parent flow.

### Small Phone, Landscape, Tablet

| Viewport | Behavior |
|---|---|
| <=360 px wide | State label can wrap to 2 lines; hide `ActionCard.detail` behind "Why"; privacy badge wraps; evidence chips become horizontally scrollable 44 px targets. |
| 361-767 px portrait | Default phone layout above. |
| Phone landscape | Split into two columns: left State/Action, right CameraTile. Bottom nav remains visible if height allows; otherwise it becomes a compact top row. |
| 768-1023 px tablet | Two-column layout: left State/Action/Privacy, right Camera/Evidence, Memory cards below full width. Bottom nav may become a left rail. |

## 6. Desktop Layout

Desktop starts at 1024 px and uses a 3-column grid.

```text
+--------------------------------------------------------------------------------+
| Beddington Live View                                      Day / Night / Auto     |
| LAN only · no cloud · no recording · no audio streaming                         |
+--------------------------+----------------------------------+------------------+
| Left column              | Center column                    | Right column     |
|                          |                                  |                  |
| +----------------------+ | +------------------------------+ | +--------------+ |
| | StateHero            | | | CameraStage                  | | | Tonight      | |
| | "Moving in the last  | | | large MJPEG stream            | | | timeline     | |
| | 4 min"               | | |                              | | +--------------+ |
| | confidence + since   | | +------------------------------+ |                  |
| +----------------------+ |                                  | +--------------+ |
| +----------------------+ | EvidenceStrip                   | | Memory       | |
| | ActionCard           | | [temp][humidity][air][light]    | | cards        | |
| +----------------------+ | [presence][rough radar est.]    | +--------------+ |
| +----------------------+ |                                  |                  |
| | RoomActionCard       | |                                  |                  |
| +----------------------+ |                                  |                  |
| +----------------------+ |                                  |                  |
| | PrivacyPanel         | |                                  |                  |
| +----------------------+ |                                  |                  |
+--------------------------+----------------------------------+------------------+
| EngineeringDrawer collapsed: raw graphs, calibration, sensor health, logs       |
+--------------------------------------------------------------------------------+
```

Column behavior:

- Left column: 280-360 px. It never scrolls independently unless viewport height is under 700 px.
- Center column: fluid. Camera keeps aspect ratio and never crops by default.
- Right column: 300-380 px. Memory cards scroll if needed.
- Engineering drawer: collapsed by default; expanded drawer is full width and can show raw graphs.

Resize behavior:

| Width | Layout |
|---|---|
| >=1280 px | 3 columns with large camera. |
| 1024-1279 px | 3 columns, narrower left/right, Memory card text truncates after two lines with "Open Memory". |
| 768-1023 px | Tablet two-column layout from Section 5. |
| <768 px | Phone layout from Section 5. |

Desktop interaction rules:

- Keyboard focus order: state -> action -> camera -> evidence -> memory -> settings -> engineering.
- No hover-only evidence. Every chart and tooltip opens on click/focus.
- Notification and sound unlock prompts appear in the left column until resolved.

## 7. Component Inventory

| Component | Data source | Props | Loading/empty/error states | Night variant | Behavior |
|---|---|---|---|---|---|
| `AppShell` | `/`, **PROPOSED** `/state.json`, real `/alerts.json` | `mode`, `privacy_badge`, `nav_items` | 401: "This link needs a valid token."; state fetch error: show camera fallback if stream works | Near-black background, no white transitions | Owns polling and responsive layout. |
| `StateHero` | **PROPOSED** `/state.json` | `state`, `label`, `confidence`, `since_ts` | Loading: "Reading the room..."; error: "State unavailable"; missing: "Not sure right now — check the camera" | Larger label, dim warm confidence chip | First visible Home component. |
| `ActionCard` | **PROPOSED** `/state.json.action` | `key`, `label`, `detail`, `target_href`, `evidence_signals` | No action: "No suggested action"; missing action: "Check the camera" | Full-width thumb-reachable button | One primary action only. |
| `RoomActionCard` | **PROPOSED** `/state.json.room_action`; real temp bands | `label`, `detail`, `evidence` | Hidden when absent | Amber accent, not red | Separate from baby-observation action. |
| `AlertStack` | Real `/alerts.json`; **PROPOSED** multi-alert schema | `alerts`, `last_notified_seq`, `device_id` | Notification denied copy; Web-Audio locked copy; no alerts hidden | T1 uses dim red, no flash | Renders T1/T2/T3 lifecycle. |
| `NotificationUnlockPrompt` | Browser APIs; **PROPOSED** alert policy | `audio_unlocked`, `notification_permission` | Unsupported: "Browser notifications are not available here." | Warm outline button | Persists until sound unlock or dismissal. |
| `PrivacyBadgeRow` | Required static copy; README privacy source | `badge_text` | Must always render on Home and Settings | Muted warm text | Exact badge copy only. |
| `PrivacyPanel` | README, liveview token behavior, Soothe behavior | `token_present`, `llm_enabled` | If LLM unknown, hide LLM line | No bright panel | Explains LAN boundary and token caveat. |
| `CameraTile` | Real `/stream.mjpg` | `src`, `mode`, `viewer_status` | Loading: dark placeholder; 503: "Camera stream is full. Try another viewer in a moment."; down: "Camera not reachable." | Dim image until tapped | Opens `CameraFullScreen`. |
| `CameraFullScreen` | Real `/stream.mjpg`, `POST /mode` | `src`, `rotate`, `mode`, `mode_auto` | Same as `CameraTile`; 401 uses token copy | Black background, low overlay opacity | Full-screen live view. |
| `EvidenceStrip` | **PROPOSED** `/state.json.evidence`; real `/readings.json` | `items[]` | No sensors: "Room readings are not wired for this session."; stale chips show age | Horizontal scroll, dim dividers | Chips open `EvidenceChartSheet`. |
| `EvidenceChip` | Same as `EvidenceStrip` | `label`, `value`, `age_s`, `status`, `source` | Missing: "no reading"; stale: "{n}s old" | 44 px min height | Shows source on focus/tap. |
| `EvidenceChartSheet` | Real `/history.json`; **PROPOSED** state evidence counts | `sensor_key`, `series`, `basis` | No history DB: "History is not stored for this session."; collecting: "Collecting readings..." | Full-height sheet with dim canvas | Draw only visible chart. |
| `MemorySummaryCard` | Real `/digest.json`; SQLite `readings`; optional `--llm` caveat | `text`, `llm_enabled` | First night: "I don't have enough history yet for a night summary."; no store: "History is not stored for this session." | Larger line height, no dense table | Shows deterministic digest text. |
| `TonightTimeline` | SQLite `cry_episodes`, `readings.motion_detected`; **PROPOSED** endpoint | `events[]` | Empty: "No timeline events yet."; no store copy | Dim markers | Does not infer sleep. |
| `WhatHelpedCard` | SQLite `soothe_outcomes`, `night_aggregates()` | `tallies[]` | Empty: "No soothe outcomes recorded yet." | Compact rows | Shows counts, not promises. |
| `PatternCard` | `night_aggregates()`; 7-night compare **PROPOSED** | `stir_hours`, `compare` | Sparse: "Not enough nights for a pattern yet." | "best guess" always visible | Shows pattern only when enough samples exist. |
| `ModeControl` | Real `/readings.json.mode`, `POST /mode`, `day_night_mode()` | `mode`, `mode_auto` | Missing sensors: hidden or disabled | Segmented control, dim active state | Cycle auto/day/night; no hover-only labels. |
| `SootheControl` | Real `/soothe.json`, `POST /soothe`, `POST /autosoothe` | `presets`, `playing`, `autosoothe`, `default` | Absent provider: hide; request fail: "Could not reach player." | Large stop/play buttons | Local nursery audio only. |
| `SettingsPanel` | Static, browser APIs, `POST /mode`, Soothe if present | `privacy`, `alerts`, `mode`, `engineering_enabled` | Browser unsupported states explicit | Low contrast surfaces within AA | Entry to Engineering. |
| `EngineeringDrawer` | Real `/history.json`, `/readings.json`, `/alerts.json`; logs **PROPOSED** | `open`, `sensor_series`, `health` | No sensors/no history/camera down/401/503 states | Dark graphs, no white canvas | Debug only; labelled "Engineering". |
| `SensorGraphPanel` | Real `/history.json` | `sensor_key`, `points`, `unit`, `bool` | `points.length<2`: "Collecting readings..." | Dim grid lines | Canvas chart per sensor. |
| `SessionError` | HTTP status | `status`, `message` | 401, 404, 503, fetch timeout | Same copy, dim palette | Keeps camera retry button visible where possible. |

## 8. UX Copy Catalogue

### Voice

| Context | Voice rules |
|---|---|
| Day | Direct, factual, short. Use room comfort words only for room conditions. |
| Night | Fewer words, bigger type, no sudden visual emphasis except T1. |
| Derived state | Include "best guess" unless the label is a direct alert or direct no-reading/no-detection state. |
| Vitals | "rough radar estimate"; no health interpretation. |
| Cry score | "cry score {score}"; never percent, probability, or chance. |
| Privacy | Exact badge plus plain LAN/token caveat. |

### State Copy

| State key | Display copy | Notes |
|---|---|---|
| `crying` | "Crying detected — {m} min" | Direct alert observation. |
| `sensor_unreliable` | "Sensors need attention" | Device/sensor issue, not a baby judgement. |
| `not_detected` false reading | "No one detected" | Only when a presence reading exists and does not detect anyone. |
| `not_detected` missing reading | "No presence reading" | Required distinct copy for missing data. |
| `caregiver_present` | "Large movement — someone's in the room" | **FUTURE**; do not claim identity until signal exists. |
| `wiggling` | "Moving in the last {n} min" | Motion observation. |
| `sleeping` | "Still for {n} min · best guess" | Internal key only; display is stillness. |
| `calm` | "Quiet, occasional movement · best guess" | Internal key only; display is movement pattern. |
| `uncertain` | "Not sure right now — check the camera" | Fallback. |

### Action Copy

| Action key | Button label | Detail |
|---|---|---|
| `none` | "No suggested action" | "Based on the current readings." |
| `check_room` | "Check the room" | "The readings need a direct look." |
| `comfort_now` | "Comfort now" | "Open Soothe or check the room." |
| `reposition_device` | "Check the device" | "A sensor may need repositioning." |
| `check_power` | "Check power" | "A device may be offline." |
| `adjust_room` | "Adjust room" | "Room temperature is outside the usual 16-20°C range." |
| `check_camera` | "Check the camera" | "Use the live view for a direct look." |

### Empty and Error Copy

| Situation | Copy | Source |
|---|---|---|
| Initial load | "Reading the room..." | **PROPOSED** client state. |
| `/state.json` unavailable | "State unavailable. Live camera may still work." | **PROPOSED** state endpoint. |
| 401 | "This link needs a valid token." | Real token gate in `liveview.py`. |
| 503 stream cap | "Camera stream is full. Try another viewer in a moment." | Real `/stream.mjpg` cap 6. |
| Camera down | "Camera not reachable." | **PROPOSED** health field from stream frame age. |
| No sensors | "Room readings are not wired for this session." | Real `--no-sensors` behavior. |
| No history store | "History is not stored for this session." | Real `--no-history`/store failure fallback. |
| First night | "I don't have enough history yet for a night summary." | Real `night_digest.summarise_night()`. |
| Notification denied | "Notifications are blocked in this browser. Alerts will stay on this screen." | Browser API. |
| Web-Audio locked | "Tap to enable sound alerts." | Browser API. |
| Soothe absent | "Soothe is not wired for this session." | Real conditional provider. |
| Soothe request failed | "Could not reach player." | Real current dashboard copy. |

### Language Policy

| Scope | Banned or required | Allowed examples | Test rule |
|---|---|---|---|
| Baby state display | Ban: safe, healthy, fine, normal, ok, okay, good, stable, asleep, sleeping, slept, likely, calm. Also ban medical certainty and SIDS/diagnosis claims. | "Still for {n} min · best guess"; "Moving in the last {n} min" | Lint `StateHero`, alert titles/messages, and action details against banned-about-baby list. |
| Internal state keys | Product-owner keys may appear in schemas/spec internals only. | `sleeping`, `calm` | Never render these keys directly as display labels. |
| Derived observation | Must include "best guess" for still/quiet/pattern labels. | "Quiet, occasional movement · best guess" | Lint derived labels for required hedge. |
| Vitals | Ban tests' reassurance words and phrases: fine, safe, healthy, normal, normally, okay, asleep, sleeping, well, good, stable, calm, settled, "breathing normally", "all good", "doing well". | "rough radar estimate"; "from radar: breathing ~14" | Apply to vitals chips, vitals sheets, and vitals answers. |
| Room conditions | Room-only labels may use `comfortable`, `normal` for pressure, and `seems okay` for air because the source modules use those words about room conditions. | "19°C · comfortable"; "pressure normal"; "air seems okay" | Allowed only when component scope is room sensor, not baby state or vitals. |
| Memory movement | The deterministic digest may describe movement patterns and must mark patterns best guess where derived. | "Movement: no movement picked up (best guess)" | Do not rewrite digest into baby-state claims. |
| Cry score | Ban probability, percent, chance, certainty language. | "cry score 0.87" | Regex rejects `%`, `probability`, `chance`, `certain`, `likely` near cry score. |
| Privacy | Must use exact badge. | "LAN only · no cloud · no recording · no audio streaming" | Exact string match on Home and Settings. |

## 9. Visual Design Tokens

No external fonts. Use system UI stack already present in `liveview.py` unless implementation chooses another local system stack.

### Color Tokens

| Token | Day | Contrast | Night | Contrast |
|---|---|---:|---|---:|
| `bg` | `#F7F5F0` | - | `#050607` | - |
| `surface` | `#FFFFFF` | - | `#101312` | - |
| `text` | `#1D2329` on day bg | 14.55:1 | `#F4EFE6` on night bg | 17.71:1 |
| `muted_text` | `#59636E` on day bg | 5.61:1 | `#B8B0A6` on night bg | 9.46:1 |
| `primary` | `#006C67` with white text | 6.29:1 | `#58C7B0` with night bg text | 9.86:1 |
| `urgent` | `#B4232C` with white text | 6.53:1 | `#FF6B6B` with night bg text | 7.31:1 |
| `attention` | `#EAB308` with day text | 8.27:1 | `#E8B154` with night bg text | 10.48:1 |
| `night_accent` | - | - | `#D28A37` with night bg text | 7.18:1 |
| `border` | `#D8D3C8` | 3:1 target for non-text | `#2B302E` | 3:1 target for non-text |

Night mode must avoid white flashes:

- Initial page background is `#050607` when `mode=night`.
- Camera placeholder is dark before the first frame.
- Modals and sheets use night `surface`, not white.

### Type Scale

| Token | Size | Line-height | Use |
|---|---:|---:|---|
| `hero` | 28 px phone / 34 px desktop | 1.15 | `StateHero.label` only. |
| `title` | 20 px | 1.25 | Cards and panels. |
| `body` | 16 px | 1.45 | Default readable text. |
| `small` | 13 px | 1.35 | Evidence metadata. |
| `micro` | 12 px | 1.3 | Badges, timestamps; never sole alert text. |

Do not scale type with viewport width. Use responsive layout, wrapping, and max-width instead.

### Spacing and Shape

| Token | Value | Use |
|---|---:|---|
| `space_1` | 4 px | Tight metadata gap. |
| `space_2` | 8 px | Chip inner gap. |
| `space_3` | 12 px | Card inner gap. |
| `space_4` | 16 px | Screen padding phone. |
| `space_5` | 24 px | Desktop column gap. |
| `radius_card` | 8 px | Cards and sheets. |
| `radius_chip` | 999 px | Evidence chips only. |
| `touch_min` | 44 px | All controls. |

Cards are for individual repeated items, action panels, modal/sheet surfaces, and tool panels only. Page sections are not nested cards.

## 10. Accessibility

| Area | Requirement | Test |
|---|---|---|
| Contrast | Day text and night text meet WCAG 2.2 AA 4.5:1; night primary controls meet at least 7:1 where possible. | Automated contrast check against tokens. |
| Touch targets | Every tappable control is at least 44 x 44 px. | Playwright/mobile viewport measurement. |
| Focus order | Keyboard order follows visual order: State, Action, Camera, Evidence, Memory, Settings, Engineering. | Tab through desktop and phone. |
| Focus visibility | Focus ring is visible in day and night palettes. | Keyboard inspection. |
| Screen readers | `StateHero` updates use `aria-live="polite"`; T1 alerts use `aria-live="assertive"`; T2 uses polite. | Screen-reader tree and DOM attributes. |
| Icon labels | Every icon-only control has `aria-label`; privacy badges have readable text. | Accessibility tree audit. |
| Motion | Respect `prefers-reduced-motion`; disable non-essential transitions and alert animations. | Emulate reduced motion. |
| Notifications | Browser Notification denial has in-page fallback. | Deny permission and raise test alert. |
| Sound | Web-Audio unlock is explicit; no hidden autoplay dependency. | Load fresh browser profile and raise alert before/after tap. |
| Camera alt | MJPEG image alt text is "Live camera view"; error states have text equivalent. | DOM audit. |
| No hover-only | Evidence, tooltips, and debug details open by click/focus/tap. | Keyboard and touch test. |
| Text fit | State labels, action buttons, badges, and nav items wrap without overlap at 320 px. | Screenshot check at 320, 360, 390 px widths. |

## 11. Performance Budget

| Budget item | Requirement | Source/status |
|---|---|---|
| `/state.json` poll | 3 s interval; payload <= 8 KB; no client derivation from display strings | **PROPOSED**. |
| `/readings.json` poll | 3 s interval while needed for evidence/mode; current dashboard already polls every 3 s | Real `liveview.py` JS. |
| `/alerts.json` poll | 2.5 s interval; payload <= 16 KB; notify once per `seq` | Real current poll interval; multi-alert payload **PROPOSED**. |
| `/history.json` poll | 5 s only while a chart/debug panel is visible; otherwise on demand or <= 30 s | Real current 5 s poll; optimized use **PROPOSED**. |
| `/digest.json` | Fetch when Memory opens and then no more than once per 60 s | Real endpoint when store exists. |
| `/soothe.json` | Fetch when Soothe control opens and after Soothe actions | Real current behavior. |
| History payload | Store-backed history max 400 points per sensor; target <= 250 KB for 10 sensors | Real `SensorStore.series(max_points=400)`; bound target **PROPOSED** for in-memory fallback. |
| Canvas draw | Draw only visible chart; one phone chart at a time; desktop debug draws visible panels only | Real canvas approach; scheduling **PROPOSED**. |
| MJPEG stream cap | Max 6 concurrent streams; 7th viewer gets 503 and UI copy | Real `_MAX_STREAM_VIEWERS=6`. |
| CPU on Pi | Avoid heavy client loops; no WebSockets; no external JS libraries; no all-chart redraw on every poll | Required tech envelope. |
| Memory | Client stores only last payloads and local alert `seq`; no recording frames or audio | Required privacy/performance envelope. |

## 12. Privacy & Security Surface

### Required Badges

Home and Settings must show exactly:

```text
LAN only · no cloud · no recording · no audio streaming
```

This wording is required because Soothe can play sound locally in the nursery; the browser does not receive audio streaming.

### Privacy Panel Copy

Use these factual points:

- The live page is token-gated. The token appears in the URL, so only share the link on a trusted LAN.
- The server is plain HTTP on the local network; do not port-forward the live-view port.
- Camera frames stream over the LAN to connected tokened viewers and are not recorded by Beddington.
- Raw audio is not streamed to the dashboard.
- Soothe plays local nursery audio from the Beddington device.
- Derived sensor history is stored locally in SQLite when history is enabled.
- Optional `--llm` digest polish may send derived event text only; show this caveat next to Memory/digest when enabled.

### Security Behaviors

| Surface | Requirement | Source |
|---|---|---|
| Token auth | Every endpoint checks query token; missing/invalid returns 401. | Real `liveview.py::is_authorised()` and handler. |
| Token in URL | Settings privacy panel explains URL-sharing risk. | Real CLI printed URL includes token. |
| Stream cap | 503 over 6 MJPEG viewers. | Real `_MAX_STREAM_VIEWERS`. |
| Cache | HTML/JSON use `Cache-Control: no-store`; stream uses no-cache/private. | Real handler. |
| No external resources | HTML must not reference CDNs, external fonts, or external scripts. | Current `_DASHBOARD_TEMPLATE` is self-contained. |
| LAN boundary | UI says local network only; no port-forward. | Real liveview docstring and CLI copy. |

## 13. Acceptance Criteria

### Product Acceptance

| ID | Criterion | Test | Principles | Data source |
|---|---|---|---|---|
| AC-01 | Home first viewport shows `StateHero`, `ActionCard`, `CameraTile`, `EvidenceStrip`, and exact privacy badge. | Phone screenshot at 390 x 844. | 1, 3, 4, 8 | **PROPOSED** `/state.json`; real `/stream.mjpg`; static privacy copy. |
| AC-02 | State labels use only observational display copy and never render internal keys `sleeping` or `calm`. | DOM text lint on `StateHero`. | 2 | **PROPOSED** `/state.json`. |
| AC-03 | Presence missing and presence false render different labels: "No presence reading" vs "No one detected". | Fixture two `/state.json` responses. | 2, 5 | Real presence raw signal; **PROPOSED** state contract. |
| AC-04 | Every state displays confidence band and opens evidence with source and age. | Click/tap each `EvidenceChip`. | 4, 5 | **PROPOSED** `/state.json.evidence`; real `/history.json`. |
| AC-05 | Room temperature action appears separately from primary state action when temp is outside 16-20 C. | Fixture temp 23 C and quiet state. | 3, 4 | Real assistant temp bands; **PROPOSED** `room_action`. |
| AC-06 | T1 cry alert beeps only after Web-Audio unlock, but visual alert appears before unlock. | Fresh browser profile, raise `POST /alert`. | 1, 6, 9 | Real `/alert`, `/alerts.json`; browser API. |
| AC-07 | Notification denied fallback displays in-page copy and keeps T1 visible. | Deny Notification permission, raise alert. | 5, 9 | Browser API; real/proposed alerts. |
| AC-08 | T2/T3 alerts follow the multi-alert schema and never trigger a night beep by default. | Schema validation and night-mode alert fixture. | 6, 10 | **PROPOSED** multi-alert `/alerts.json`. |
| AC-09 | `CameraTile` handles 503 stream cap with specified copy. | Simulate 7th stream response. | 5, 10 | Real `/stream.mjpg` cap. |
| AC-10 | `CameraTile` handles 401 with token copy and no broken image-only state. | Open without token. | 5, 8 | Real token gate. |
| AC-11 | Memory first-night/no-store states render specified empty copy. | Disable store and open Memory. | 5, 7 | Real `/digest.json` absence; real store fallback. |
| AC-12 | Memory "what helped" uses soothe tallies and shows counts only, no promise of future effect. | Fixture `night_aggregates().soothe_tallies`. | 7 | Real SQLite `soothe_outcomes`; `night_aggregates()`. |
| AC-13 | 7-night comparison is hidden or marked **PROPOSED** until endpoint exists. | Inspect Memory with no compare field. | 5, 7 | **PROPOSED** aggregate contract. |
| AC-14 | Engineering raw graphs are behind Settings and labelled "Engineering". | Phone navigation test. | 1, 4 | Real `/history.json`; UI structure. |
| AC-15 | No external network assets are requested by the page. | Browser network audit. | 8, 10 | Real `_DASHBOARD_TEMPLATE` self-contained HTML envelope. |
| AC-16 | `/history.json` charts draw only visible panels and stay within payload budget. | Performance test with 10 sensors x 400 points. | 10 | Real `SensorStore.series`; **PROPOSED** client scheduling. |
| AC-17 | Night mode uses night tokens, no white flash, and readable State/Action at arm's length. | Screenshot and contrast audit in `mode=night`. | 6, 9 | Real `/readings.json.mode`; design tokens. |
| AC-18 | All controls are keyboard reachable and at least 44 px on touch viewports. | Accessibility audit at phone and desktop sizes. | 9 | **PROPOSED** static UI behavior contract. |
| AC-19 | Privacy panel mentions token-in-URL, LAN trust boundary, no recording, no audio streaming, local Soothe audio, and optional `--llm` caveat. | Text assertion in Settings. | 8 | Real README/privacy, liveview token behavior, and Soothe endpoints. |
| AC-20 | Cry score is never rendered as percent/probability/chance. | Language lint on alert and evidence text. | 2, 9 | Real cry score field/message. |
| AC-21 | Radar vitals are hidden without breathing lock and labelled rough radar estimate when shown. | Fixture with heart only, then breathing+heart. | 2, 5 | Real `_dashboard_fields()` and `assistant._vitals_phrase()`. |
| AC-22 | State computation is server-side; client does not parse `/readings.json` display strings for state. | Code review/static check. | 2, 10 | **PROPOSED** `/state.json`. |
| AC-23 | Motion transition counts come from server raw samples, not downsampled chart points. | Compare dense fixture with downsampled `/history.json`. | 2, 4, 10 | Real SQLite `readings`; **PROPOSED** state evidence. |
| AC-24 | FUTURE caregiver identity state is not emitted unless a named caregiver identity/person-classification signal exists. | Fixture lacks FUTURE signal; assert no `caregiver_present`. | 2, 5 | **FUTURE** caregiver identity signal. |

### Safety-Language Test Plan

Scope every rendered string before linting:

| Scope | Components | Banned tokens/patterns | Required tokens/patterns |
|---|---|---|---|
| `baby_state_display` | `StateHero`, `ActionCard.detail`, T1/T2 baby-related alerts | `safe`, `healthy`, `fine`, `normal`, `ok`, `okay`, `good`, `stable`, `asleep`, `sleeping`, `slept`, `likely`, `calm`; medical/SIDS terms | Observational label; `best guess` for derived still/quiet states. |
| `vitals` | Vitals chip, vitals evidence sheet, vitals alert/evidence | Above plus `normally`, `well`, `settled`, phrases `breathing normally`, `he s okay`, `rayan is okay`, `all good`, `perfectly fine`, `doing well` | `rough radar estimate` or `from radar`; no interpretation. |
| `room` | Temperature, humidity, pressure, air, light chips/cards | Baby-state terms only when used about baby; do not ban room `comfortable`, pressure `normal`, or air `seems okay` | Source-specific room labels from `assistant.py`. |
| `cry_score` | T1 message, evidence score | `%`, `probability`, `chance`, `certain`, `likely` within same sentence as cry score | `cry score {decimal}`. |
| `privacy` | `PrivacyBadgeRow`, `PrivacyPanel` | Alternative badge strings | Exact badge on Home and Settings. |
| `memory` | Digest, patterns, what helped | Baby health/safety terms; future-effect promises | `best guess` for derived patterns. |

Recommended lint fixtures:

```text
1. Render every state fixture from Section 2.
2. Render every alert fixture from Section 4.
3. Render every empty/error string from Section 8.
4. Render room labels with "comfortable", pressure "normal", and air "seems okay" under room scope.
5. Render vitals with breathing lock and confirm no reassurance tokens.
6. Render cry score 0.87 and confirm no probability wording.
7. Render privacy badge and exact-match it.
```

## 14. Out-of-Scope & FUTURE

Out of scope for this UI specification:

- Implementing the UI.
- Changing Python endpoints, tests, config, README, or the plan.
- Adding WebSockets or server push.
- Adding cloud accounts, vendor notification services, or off-LAN push alerts.
- Making medical, diagnostic, SIDS, apnoea, fever, oxygen, or blood-pressure claims.
- Recording video/audio or adding audio streaming to the browser.
- Reworking the existing Soothe audio system.

FUTURE items requiring new signals or contracts:

| Item | Missing signal/contract |
|---|---|
| Caregiver identity | Trusted identity source or person-classification signal. |
| Camera person classification | Local vision model output; not current MJPEG stream alone. |
| Multi-alert push beyond LAN | Secure push infrastructure and user consent; outside LAN-only envelope. |
| Rich device logs in Engineering | Server log endpoint with redaction rules. |
| 7-night "what changed" comparison | Stable aggregate endpoint over `night_aggregates()` plus current-night summary. |
| Camera health in state | Frame-age/error health contract for `/state.json`. |
| Sensor stale health in state | Per-signal age/error health contract for `/state.json`. |
