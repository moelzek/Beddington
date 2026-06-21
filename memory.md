# memory.md — Lullaby single source of truth

> This is the canonical snapshot of changing project facts. Other documents explain or sequence the work; this file wins when they disagree.

## Project

- **Name:** Lullaby.
- **Repository:** `~/Code/Labie` (GitHub: `moelzek/labie`).
- **Owner:** Mo, a physician-scientist who is new to software and hardware, has ADHD, and has a newborn.
- **Purpose:** a privacy-first baby-monitor companion that helps parents **aggregate** overnight patterns and **act** through a future soothe-before-escalation loop.
- **Positioning:** an assistive night notebook and companion, **not a medical guardian** and not a replacement for adult supervision or an approved baby monitor.

## Current status

- **Active tier:** Tier 1 — single-preset soothe before escalation, explicitly approved by Mo on 2026-06-21. The first slice is laptop-first dry-run soothing before parent notification.
- **Repository state:** Lab Witness has been retired and preserved under `Archive/`.
- **Code state:** Python package under `src/lullaby/` with WAV/microphone adapters, YAMNet TFLite detection, deterministic cry-event tracking, Tier 1 dry-run soothe preset, local logs, morning digest, notifications, and optional LLM polish.
- **Development mode:** laptop-first using sample `.wav` files and mocks. The Raspberry Pi rig is not required for development.
- **Acceptance result:** the included CC0 sample still produces Tier 0 outputs; the Tier 1 demo config records one dry-run soothe preset before escalation; generated uterine-style whoosh, white-noise, heartbeat-style, and soothing-music WAV assets exist; soothe playback can loop short files for long configured windows; the hardware-free test suite passes.
- **Next gate:** test real local playback of the generated soothing audio files at low laptop volume, including a longer looped run, then decide whether to bench-test the Pi speaker/amplifier.

## Locked decisions

| Area | Decision |
|---|---|
| Product value | Prioritise **aggregate** (nightly patterns) and **act** (soothe before escalation), not merely re-reporting crying a parent can hear. |
| Privacy | Raw audio/video never leaves the device. Only derived events, features, or short text may reach an optional cloud LLM. |
| Claims | No medical or safety claims. Never claim SIDS, apnoea, fever, diagnosis, or breathing as a vital sign. |
| Inference language | Cry reason, hunger, nappy, warmth, and similar interpretations are always labelled **best guess**. |
| Safety | Hot Pi/Hailo compute sits in a vented base. A companion/toy may sit beside the cot, never in the cot or sleep surface. |
| Core logic | Detection, thresholds, timers, debounce, and event generation are deterministic. |
| LLM | Optional, provider-agnostic, environment-configured, and behind a flag. The complete app works with it off. |
| Development | Hardware-free first. Audio/video files and mock sensors use the same adapter interfaces as real Pi hardware. |
| Scope | Build Tier 1 only. Tiers 2–5 still require Mo’s explicit approval and their safety gates. |

## Hardware on hand

These facts were migrated from the retired Lab Witness inventory.

| Hardware | State | Planned Lullaby role |
|---|---|---|
| Raspberry Pi 5, 4GB | On hand | Deployment hub/orchestrator |
| Active Cooler + official 27W USB-C PSU | On hand | Cooling and power for the vented base |
| AI HAT+ 26 TOPS, Hailo-8 | On hand and previously fitted | Later video inference; not needed for Tier 0 audio |
| Camera Module 3 ×2 | On hand | Later daytime video; standard modules are not suitable for dark-room IR work |
| Pi 5 camera adapter cable | On hand; camera was previously detected | Later camera connection |
| USB mini microphone | On hand | Tier 0 live audio input on the Pi |
| 3W 4Ω speaker + MAX98357 I2S amplifier | On hand | Bench audio-output test now; Tier 1 soothe output only after explicit approval |
| 0.91-inch I²C OLED ×3 | On hand | Later companion eyes/status |
| BS-16 mini speaker | On hand | Tier 1 soothe output; may require an amplifier |
| Seeed MR60BHA2 60GHz mmWave sensor with XIAO ESP32C6 | On hand, quantity 1 | Later presence/gross movement; breathing may be shown only as a non-medical trend after mentor safety sign-off |
| Pimoroni BME688 4-in-1 air quality breakout | On hand, quantity 1 | Later room temperature/humidity and experimental nappy-VOC best guess after calibration and hygiene review |
| microSD card, 32GB | On hand | Pi OS and deployment |
| Breadboards, jumper wires, electronics bench | On hand | Prototyping |

## Hardware to buy or verify later

- **Tier 0:** no purchase is required for laptop development. Verify microphone quality and placement before Pi deployment.
- **Tier 1:** verify whether the BS-16 speaker needs a small amplifier.
- **Tier 2:** NoIR Camera Module 3 plus an 850nm IR illuminator if dark-room video is required; cot-safe mount with cables out of reach.
- **All Pi deployment:** vented base/enclosure and an overnight thermal check.
- **Tier 3:** MR60BHA2 is owned; later verify cot-distance signal quality, mounting, and ESPHome/MQTT integration only after the radar gate is approved.
- **Tier 4:** BME688 is owned; later verify placement, hygiene, calibration, and nappy-VOC limits only after the environment gate is approved.
- **Tier 5:** optional MLX90640 only after the relevant gate is approved.

## Architecture boundary

```text
audio/video/sensors
        |
        v
local adapters -> local deterministic detection/timing -> local event log
                                                    |
                                                    +-> local notification
                                                    |
                                                    +-> optional LLM: derived text/features only
```

Raw recordings remain local. Generated logs must not contain raw media or secrets.

## Tier plan

| Tier | Outcome | Gate |
|---|---|---|
| **0 — Spine** | WAV/mic → YAMNet baby-cry detection → sustained-cry events → JSON/readable night log → rule-based morning digest → debounced console/desktop notification | Complete |
| **1 — Act** | One selected soothe preset before notification; optional “likely hungry” best guess from cry + time since feed | Active; laptop dry-run slice implemented |
| **2 — Video** | File/OpenCV laptop adapter and picamera2/Hailo Pi adapter; active/still and face-covered observations | Mo must approve; privacy and false-alarm review |
| **3 — Radar** | Presence and gross movement; breathing may be shown only as a non-medical trend | Mentor safety sign-off; never alarms |
| **4 — Environment** | Room temperature/humidity and nappy-VOC best guess | Calibration and hygiene review |
| **5 — Thermal** | Relative warmth trend only | Highest-risk optional tier; never fever detection |

## Tier 0 acceptance

On a laptop with no hardware attached:

1. Install from documented commands.
2. Run an included sample cry recording.
3. See timestamped cry detections with confidence.
4. Receive one notification only after the configured sustained duration.
5. Produce a machine-readable night log and a readable text log.
6. Generate a plain-English morning digest.
7. Run tests without downloading a model or requiring a cloud key.

## Tier 1 first-slice acceptance

On a laptop with no speaker hardware attached:

1. Run the included sample cry recording with `config/tier1-demo.toml`.
2. See a `SOOTHE` line in the readable night log before any `NOTIFIED` line.
3. See the morning digest mention one soothe preset before escalation.
4. Run tests without playing audio, downloading a model, or requiring a cloud key.

## Tier 1 audio assets

Local generated placeholder WAVs live under `assets/soothe/`:

1. `uterine_whoosh.wav` — stronger synthetic womb-like rumble and whoosh, not a recording.
2. `white_noise.wav`
3. `heartbeat.wav` — heartbeat-style pulses, not a medical recording.
4. `soothing_music.wav`

They are for testing the preset and audio-output path. They do not imply that a
given sound will soothe a baby. The files are short, but playback can loop the
selected preset for long configured windows. Lullaby should play one selected
mode, such as `white_noise`, `heartbeat`, or `soothing_music`, rather than
cycling through all sounds automatically. `uterine_whoosh` remains available as
an optional synthetic output-test preset.

## Living-document protocol

1. Read this file at the start of each session.
2. Put mutable facts here once; link from other documents.
3. Add a dated changelog line for every canonical decision or status change.
4. Keep external persistent memory out of repository scope. It may be updated separately, but the repo must remain understandable without it.

## Changelog

- **2026-06-21** — Mo corrected the Tier 1 product model: Lullaby should use one selected soothe preset, not cycle through all sounds automatically. Config now supports `soothe.preset` and named presets; default preset is `white_noise`.
- **2026-06-21** — Renamed lowercase `agents.md` to root `AGENTS.md` and added Codex-specific loading notes so Codex sessions read the project operating manual by default while `CLAUDE.md` remains the Claude Code router.
- **2026-06-21** — Changed Tier 1 soothing from one-shot clip playback to looped playback with separate `play_seconds` and `wait_seconds`, reflecting Mo’s note that settling can take about 30 minutes rather than a few seconds.
- **2026-06-21** — Added a stronger generated `uterine_whoosh.wav` asset. It is a synthetic womb-like output-test sound, not a recording or soothe claim.
- **2026-06-21** — Added generated local Tier 1 soothe assets: white noise, heartbeat-style pulses, and soothing music, plus the reproducible generator script, asset metadata test, and config paths. Real playback remains the next gate and should start at low laptop volume.
- **2026-06-21** — Mo explicitly approved starting Tier 1. Implemented the first laptop-first slice: configurable dry-run soothing, `--soothe` CLI enablement, Tier 1 demo config, soothe events in JSON/readable logs, soothe mention in the morning digest, and tests for soothe-before-notify and settle-before-notify paths. Tiers 2–5 remain gated.
- **2026-06-21** — Added the owned 3W 4Ω speaker and MAX98357 I2S amplifier to the hardware inventory. It may be bench-tested on the Pi now; product soothe-output integration remains Tier 1-gated.
- **2026-06-21** — Added one Seeed MR60BHA2 60GHz mmWave sensor with XIAO ESP32C6 and one Pimoroni BME688 4-in-1 air quality breakout to the owned hardware inventory. Tier 0 remains active; radar and environment work remain gated later-tier scope.
- **2026-06-19** — Merged `codex/lullaby-tier0` into `main`: promoted the `src/lullaby/` Tier 0 audio spine, CLI, config, sample-data workflow, logs, morning digest, optional derived-text-only LLM polish, and hardware-free tests as the canonical implementation. Kept Lab Witness material archived and ignored local `.gbrain-source`.
- **2026-06-18** — Pivoted the repository from Lab Witness to **Lullaby** as the main project. Archived Lab Witness build documents, prompts, reviewer skills, and devlog without deleting them. Promoted the baby-monitor evaluation and build plan into project-core documents. Migrated reusable hardware facts, locked privacy/safety/LLM boundaries, and set Tier 0 audio as the only active build scope.
- **2026-06-18** — Built and acceptance-tested Tier 0: official YAMNet TFLite baby-cry scoring, laptop WAV and optional live microphone adapters, deterministic sustained-cry/release/cooldown logic, local JSON and readable logs, rule-based morning digest, console/desktop notification, optional derived-text-only LLM polish, public CC0 sample audio, and hardware-free tests. Tier 1 remains blocked pending Mo’s explicit approval.
