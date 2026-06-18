# memory.md — Lullaby single source of truth

> This is the canonical snapshot of changing project facts. Other documents explain or sequence the work; this file wins when they disagree.

## Project

- **Name:** Lullaby.
- **Repository:** `~/Code/Labie` (GitHub: `moelzek/labie`).
- **Owner:** Mo, a physician-scientist who is new to software and hardware, has ADHD, and has a newborn.
- **Purpose:** a privacy-first baby-monitor companion that helps parents **aggregate** overnight patterns and **act** through a future soothe-before-escalation loop.
- **Positioning:** an assistive night notebook and companion, **not a medical guardian** and not a replacement for adult supervision or an approved baby monitor.

## Current status

- **Active tier:** Tier 0 — audio spine.
- **Repository state:** Lab Witness has been retired and preserved under `Archive/`.
- **Code state:** no application code yet at the documentation-pivot commit.
- **Development mode:** laptop-first using sample `.wav` files and mocks. The Raspberry Pi rig is not required for development.
- **Next gate:** run an included sample recording on a laptop and produce detected cry events, a night log, a morning digest, and one debounced sustained-cry notification.

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
| Scope | Build Tier 0 only until Mo explicitly approves Tier 1. |

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
| 0.91-inch I²C OLED ×3 | On hand | Later companion eyes/status |
| BS-16 mini speaker | On hand | Tier 1 soothe output; may require an amplifier |
| microSD card, 32GB | On hand | Pi OS and deployment |
| Breadboards, jumper wires, electronics bench | On hand | Prototyping |

## Hardware to buy or verify later

- **Tier 0:** no purchase is required for laptop development. Verify microphone quality and placement before Pi deployment.
- **Tier 1:** verify whether the BS-16 speaker needs a small amplifier.
- **Tier 2:** NoIR Camera Module 3 plus an 850nm IR illuminator if dark-room video is required; cot-safe mount with cables out of reach.
- **All Pi deployment:** vented base/enclosure and an overnight thermal check.
- **Tier 3+:** MR60BHA2 radar with its ESP32 bridge, BME688, and optional MLX90640 only after the relevant gate is approved.

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
| **0 — Spine** | WAV/mic → YAMNet baby-cry detection → sustained-cry events → JSON/readable night log → rule-based morning digest → debounced console/desktop notification | Active |
| **1 — Act** | Soothe ladder: lullaby/white noise/recorded parent voice before notification; optional “likely hungry” best guess from cry + time since feed | Mo must approve |
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

## Living-document protocol

1. Read this file at the start of each session.
2. Put mutable facts here once; link from other documents.
3. Add a dated changelog line for every canonical decision or status change.
4. Keep external persistent memory out of repository scope. It may be updated separately, but the repo must remain understandable without it.

## Changelog

- **2026-06-18** — Pivoted the repository from Lab Witness to **Lullaby** as the main project. Archived Lab Witness build documents, prompts, reviewer skills, and devlog without deleting them. Promoted the baby-monitor evaluation and build plan into project-core documents. Migrated reusable hardware facts, locked privacy/safety/LLM boundaries, and set Tier 0 audio as the only active build scope.
