# memory.md — Lullaby single source of truth

> This is the canonical snapshot of changing project facts. Other documents explain or sequence the work; this file wins when they disagree.

## Project

- **Name:** Lullaby.
- **Repository:** `~/Code/Labie` (GitHub: `moelzek/labie`).
- **Owner:** Mo, a physician-scientist who is new to software and hardware, has ADHD, and has a newborn.
- **Purpose:** a privacy-first baby-monitor companion that helps parents **aggregate** overnight patterns and **act** through a future soothe-before-escalation loop.
- **Positioning:** an assistive night notebook and companion, **not a medical guardian** and not a replacement for adult supervision or an approved baby monitor.

## Current status

- **Active tier:** Tier 2A — bench-only local video plumbing. Mo asked on 2026-06-23 to move to the next steps directly without waiting for another approval; the scope remains bounded by the Tier 2 privacy, false-alarm, mount, and dark-room gates.
- **Repository state:** Lab Witness has been retired and preserved under `Archive/`.
- **Code state:** Python package under `src/lullaby/` with WAV/microphone adapters, YAMNet TFLite detection, deterministic cry-event tracking, Tier 1 dry-run soothe preset, deterministic quiet-check windows, short soothe playback preview, Tier 2A camera-smoke metadata checks, deterministic local visual-change metrics, Pi camera-linked visual-change smoke tests, local logs, morning digest, notifications, and optional LLM polish.
- **Development mode:** laptop-first using sample `.wav` files and mocks, with Pi bench tests only for gated hardware checks.
- **Acceptance result:** the included CC0 sample still produces Tier 0 outputs; the Tier 1 demo config records one dry-run soothe preset before escalation; generated uterine-style whoosh, white-noise, heartbeat-style, and soothing-music WAV assets exist; low-volume laptop preview and short looped playback worked for the main generated presets; soothe playback can loop short files for long configured windows; deterministic quiet-check tests pass in hardware-free mode; Pi Bluetooth playback worked through an Anker SoundCore; USB microphone capture and live YAMNet listen smoke tests worked on the Pi; the synced Pi checkout passes the hardware-free suite and Tier 1 sample; the attached Camera Module 3 is detected as `imx708`; `lullaby camera-smoke` passes on the Pi and leaves only a derived JSON report by default; `lullaby visual-change` passes locally and on the Pi using generated local PGM frames; `lullaby camera-change` passes on the Pi and leaves only derived `visual-change.json` by default; `camera-mount-plan.md` documents the cot-safe physical gate for future nursery camera use.
- **Next gate:** choose the actual nursery camera mount location, mark the 3-foot exclusion zone, sketch or photograph the cable route and vented Pi base, run a bench thermal check, and then run baby-absent nursery smoke tests that write only derived JSON. Nursery deployment, active safety claims, face-covered claims, Hailo, and night-vision work remain gated. MAX98357 is deferred by Mo.

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
| Parent app | Multiple parent devices and family sharing are desired later. Under the current privacy rule they start with derived alerts, logs, and digests; raw live video on phones requires a separate explicit privacy-boundary decision. |
| Sensors | BME688 can be bench-read after the current camera physical gate, but product environment use is Tier 4. VL53L0X is a near-term mount/enclosure utility. MR60BHA2 is Tier 3 after safety sign-off. HC-SR04, HC-SR501-style PIR, INMP441, OLEDs, and servos stay bench-only until their gates. |
| Scope | Build only the active approved tier. Future tier expansions still require Mo's explicit approval and their safety gates. |

## Hardware on hand

These facts were migrated from the retired Lab Witness inventory.

| Hardware | State | Planned Lullaby role |
|---|---|---|
| Raspberry Pi 5, 4GB | On hand | Deployment hub/orchestrator |
| Active Cooler + official 27W USB-C PSU | On hand | Cooling and power for the vented base |
| AI HAT+ 26 TOPS, Hailo-8 | On hand and previously fitted | Later video inference; not needed for Tier 0 audio |
| Camera Module 3 ×2 | On hand; one attached to the Pi, detected as `imx708`, and passed a local still-capture smoke test | Later daytime video; standard modules are not suitable for dark-room IR work |
| Pi 5 camera adapter cable | On hand; current camera connection works | Later camera connection |
| USB mini microphone | On hand | Tier 0 live audio input on the Pi; use before I²S mics |
| MAX98357 I²S amplifier | On hand, quantity 2 | Tier 1 bench audio output |
| 3W 4Ω speaker | On hand, quantity 4 | Wired to MAX98357 for Tier 1 soothe output tests |
| INMP441 MEMS microphone | On hand, quantity 4 | I²S audio input; advanced, use USB/Bluetooth mic first |
| 0.96-inch I²C OLED | On hand, quantity 4 | Later companion eyes/status |
| 0.91-inch I²C OLED | On hand, quantity 2 | Later companion eyes/status |
| BS-16 mini speaker | On hand | Tier 1 soothe output; may require an amplifier |
| PCA9685 16-channel servo driver | On hand, quantity 3 | I²C servo driver; use this for servos, with separate servo power |
| MG996R metal-gear servo | On hand, quantity 4 | Later movement/prototyping via PCA9685; not cot deployment by default |
| Miuzei 9g micro servo | On hand, quantity 10 | Later light movement/prototyping via PCA9685 |
| SG90 9g micro servo | On hand, quantity 10 | Later light movement/prototyping via PCA9685 |
| USB-C PD trigger board | On hand, quantity 5 | Utility power board, especially separate servo power experiments |
| Seeed MR60BHA2 60GHz mmWave sensor with XIAO ESP32C6 | On hand, quantity 1 | Later presence/gross movement; breathing may be shown only as a non-medical trend after mentor safety sign-off |
| Pimoroni BME688 4-in-1 air quality breakout | On hand, quantity 1 | Later room temperature/humidity and experimental nappy-VOC best guess after calibration and hygiene review |
| HC-SR04 ultrasonic distance sensor | On hand, quantity 5 | GPIO distance/proximity; needs voltage divider; optional utility only, not baby-state inference |
| HC-SR501-style D-SUN PIR motion sensor | On hand, quantity 1 | Bench-only passive infrared motion/proximity experiment; not baby-state inference and not a safety signal |
| VL53L0X laser distance/ToF sensor | On hand, quantity 5 | I²C distance/proximity; preferred distance sensor over HC-SR04 |
| microSD card, 32GB | On hand | Pi OS and deployment |
| Breadboards, jumper wires, wire, screws | On hand, many | Prototyping |

## Current bench GPIO occupancy

Mo reported this Raspberry Pi 5 physical-pin occupancy on 2026-06-27. Treat it
as a live wiring map, not as a safety validation; confirm each module pin label
and Pi pin function before powering the bench rig.

| Hardware | Reported occupied physical pins | Notes |
|---|---|---|
| Pimoroni BME688 4-in-1 air quality breakout | 1, 3, 5, 9 | Expected I²C pattern: 3.3V, SDA/GPIO2, SCL/GPIO3, GND |
| MAX98357 I²S amplifier | 35, 12, 40, 4, 6 | Expected I²S pattern: GPIO19/LRC, GPIO18/BCLK, GPIO21/DIN, 5V, GND |
| HC-SR501-style D-SUN PIR motion sensor | 7, 14, 2 | Bench-only; if powered from 5V, PIR signal to GPIO must be level-safe before entering the Pi |
| VL53L0X laser distance/ToF sensor | 19, 20, 16, 15 | Verify before powering: physical pin 19 is GPIO10/SPI0 MOSI, not 3.3V or 5V |

## Hardware to buy or verify later

- **Tier 0:** no purchase is required for laptop development. Verify microphone quality and placement before Pi deployment.
- **Tier 1:** verify whether the BS-16 speaker needs a small amplifier.
- **Tier 2:** NoIR Camera Module 3 plus an 850nm IR illuminator if dark-room video is required; actual cot-safe mount choice, physical mock-up, and cable route with all parts out of reach.
- **All Pi deployment:** vented base/enclosure and an overnight thermal check.
- **Audio hardware:** use USB/Bluetooth microphones first; INMP441 I²S microphones are advanced and should wait until the basic Pi audio loop works.
- **Servo hardware:** servos must be driven through PCA9685 and separate power; do not power servos from Pi GPIO pins.
- **Tier 3:** MR60BHA2 is owned; later verify cot-distance signal quality, mounting, and ESPHome/MQTT integration only after the radar gate is approved.
- **Tier 4:** BME688 is owned; a bench-only local read can happen after the current camera physical gate, but nursery/product use waits for placement, hygiene, calibration, and environment-gate approval.
- **Utility sensors:** VL53L0X is the preferred distance/proximity sensor. HC-SR04 may be useful for bench proximity checks or mount/enclosure experiments, but needs a voltage divider and should not be used to infer baby state. The HC-SR501-style PIR sensor is bench-only motion/proximity hardware and must not be used as a safety signal.
- **Tier 5:** optional MLX90640 only after the relevant gate is approved.

Detailed wiring notes, smoke-test snippets, and the safe bench-test order live in
[hardware-guide.md](hardware-guide.md).

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
| **1 — Act** | One selected soothe preset before notification; optional “likely hungry” best guess from cry + time since feed | Implemented through quiet-check smoke gates; MAX98357 deferred |
| **2 — Video** | File/OpenCV laptop adapter and picamera2/Hailo Pi adapter; active/still and face-covered observations | Active as Tier 2A bench-only local plumbing; nursery deployment and interpretation remain gated |
| **3 — Radar** | Presence and gross movement; breathing may be shown only as a non-medical trend | Mentor safety sign-off; never alarms |
| **4 — Environment** | Room temperature/humidity and nappy-VOC best guess | Calibration and hygiene review |
| **5 — Thermal** | Relative warmth trend only | Highest-risk optional tier; never fever detection |
| **Parent app/reliability layer** | Multiple parent devices, family sharing, push alerts, and connection/power-health alerts | After local core and hardware gates; auth, encryption, pairing, revocation, and privacy review |

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

## Future soothe verification

When soothing is playing, audio ML remains the primary signal for whether
crying is still detected. Future work should add quiet-check windows and an
echo-cancellation experiment. Camera/video and radar/breathing may later add
supporting context, but must not prove the baby is safe, asleep, or breathing
normally. If signals disagree, Lullaby should keep checking or notify the
parent. Log wording must stay honest: “crying no longer detected”, not “baby is
asleep” or “baby is safe”.

## Living-document protocol

1. Read this file at the start of each session.
2. Put mutable facts here once; link from other documents.
3. Add a dated changelog line for every canonical decision or status change.
4. Keep external persistent memory out of repository scope. It may be updated separately, but the repo must remain understandable without it.

## Changelog

- **2026-06-27** — Recorded Mo's current Raspberry Pi 5 bench GPIO occupancy: BME688 on pins 1/3/5/9, MAX98357 on 35/12/40/4/6, HC-SR501-style PIR on 7/14/2, and VL53L0X on 19/20/16/15. Added a warning that the map is not a safety validation and VL53L0X pin 19 needs verification before powering.
- **2026-06-27** — Added Mo's HC-SR501-style D-SUN PIR motion sensor to the owned inventory as bench-only motion/proximity hardware, not baby-state inference and not a safety signal.
- **2026-06-24** — Removed the extra app-store-style roadmap item at Mo's request and clarified sensor timing. BME688 can be bench-read after the current camera physical gate, but nursery/product use remains Tier 4 after placement, hygiene, and calibration review. VL53L0X is the near-term utility sensor for mount/enclosure checks; MR60BHA2 stays Tier 3 after safety sign-off; HC-SR04, INMP441, OLEDs, and servos remain bench-only until their gates.
- **2026-06-23** — Mapped Mo's baby-monitor app screenshot requirements into the roadmap: smart audio/video monitoring, smart noise and cry detection, instant noise/connection/power alerts, advanced night vision, multiple parent devices, family sharing, and local continuous viewing. The placement keeps current safety/privacy boundaries: night vision stays Tier 2-gated, parent sharing starts with derived alerts/logs/digests, and raw live video on phones would require a separate future privacy decision.
- **2026-06-23** — Added `camera-mount-plan.md`, the Tier 2A physical gate before any nursery camera use. The plan uses CPSC baby-monitor cord guidance, AAP safe-sleep guidance, and Raspberry Pi camera-cable guidance; requires all hardware, mounts, power, straps, tape tails, and cables to stay outside a strict 3-foot exclusion zone; keeps Pi/Hailo compute in a vented base; blocks cot-mounted parts and dangling cables; and still requires a chosen physical location, marked exclusion zone, cable route, bench thermal check, and baby-absent derived-JSON smoke test before nursery video.
- **2026-06-23** — Added `lullaby camera-change`, a Tier 2A bench command that captures two short local BMP frames through the Pi Camera Module 3, runs the deterministic visual-change metric, writes derived `visual-change.json`, and deletes raw frames by default. Tests pass locally and on the Pi with 46 tests. The Pi camera-linked smoke test used 160×120 captures, produced `visual_change_detected` with a changed-pixel ratio of about 0.64 in the live bench scene, and left only `output/pi-camera-change/visual-change.json`.
- **2026-06-23** — Added `lullaby visual-change`, a deterministic Tier 2A command that compares two local PGM/PPM frames and writes only derived metrics: mean absolute difference, changed-pixel ratio, thresholds, and an observation of `visual_change_detected` or `little_visual_change_detected`. Wording states this is not a safety, sleep, breathing, or face-covering assessment. Tests pass locally and on the Pi with 43 tests; a Pi smoke test over generated local frames produced a 0.5 changed-pixel ratio and then removed the temporary raw test frames.
- **2026-06-23** — Mo authorised moving directly to the next steps without waiting for another approval. Added `tier2-video-gate.md` and implemented `lullaby camera-smoke`, which inspects local JPEG/PNG files for hardware-free tests or captures one local Pi frame via `rpicam-still`, writes derived `camera-smoke.json` metadata, and deletes the raw test frame by default. Tests pass locally and on the Pi with 39 tests. The Pi command produced a 640×480 JPEG metadata report for the `imx708` camera and left only `camera-smoke.json` in the output directory.
- **2026-06-23** — Mo asked to put the MAX98357 wired-speaker bench test aside and move on. The attached Camera Module 3 is detected by `rpicam-hello --list-cameras` as `imx708` at up to 4608×2592. A no-preview `rpicam-still` smoke test captured a local 640×480 JPEG on the Pi, verified dimensions and metadata, and deleted the test image without copying raw frames off-device. Tier 2 product video work still needs the privacy/false-alarm gate before implementation.
- **2026-06-23** — Trusted SSH access to the Pi is working from the Mac through a dedicated local key for `lab@lab.powerhub`. Synced the quiet-check code to `~/Labie` on the Pi, confirmed the Pi hardware-free suite passes, confirmed the Pi Tier 1 sample logs `SOOTHE` before `NOTIFIED`, and ran a 12-second live USB-microphone smoke test that analysed 17 local windows and detected no sustained crying, as expected for a non-cry test. The next hardware gate is the powered-off MAX98357 plus 3W speaker bench test.
- **2026-06-23** — Implemented deterministic Tier 1 quiet-check windows. When enabled, Lullaby pauses playback, listens with the local audio detector, requires repeated quiet checks before logging “crying no longer detected”, and stops playback when escalating to a parent notification. Tests cover quiet confirmation, failed checks, unresolved recordings, playback pause/resume/stop, and wording guardrails.
- **2026-06-23** — Confirmed the USB microphone appears on the Pi as `USB PnP Sound Device` / `PCM2902 Audio Codec`. Raw ALSA recording and playback worked, then Lullaby's microphone adapter captured live windows after adding a fallback that records at the mic's native rate and resamples internally to 16 kHz. A live `lullaby listen` smoke test downloaded YAMNet, analysed 12 microphone windows locally, wrote output logs, and did not detect sustained crying, as expected for a non-cry test.
- **2026-06-23** — Confirmed Pi Bluetooth audio output through an Anker SoundCore. `preview-soothe` played the generated soothing-music preset successfully, and the Pi volume was returned to 30% afterwards. Next gate is a powered-off MAX98357 plus 3W speaker bench test at low volume.
- **2026-06-22** — Added a `preview-soothe` CLI command so Mo can run a short low-volume selected-preset playback test on the Pi without starting cry detection. The next gate remains confirming Bluetooth speaker output before MAX98357 wiring.
- **2026-06-21** — Added `hardware-guide.md` with Mo’s servo, power, audio, microphone, distance-sensor, and OLED wiring notes, including install snippets, reference links, and a safer bench-test order.
- **2026-06-21** — Confirmed short looped laptop playback worked for the selected white-noise soothe preset. Next gate is Pi audio output with a Bluetooth speaker before wiring the MAX98357 amplifier.
- **2026-06-21** — Confirmed low-volume laptop preview playback worked for the generated Tier 1 soothe presets. Next gate is a short looped real playback test before Pi speaker/amplifier bench testing.
- **2026-06-21** — Added future roadmap work for verifying whether crying has stopped while a soothe preset is playing: quiet-check windows, echo-cancellation experiment, camera context, and radar/breathing context under strict non-medical wording and never as sole proof of safety.
- **2026-06-21** — Added user-mentioned HC-SR04 ultrasonic distance sensor to inventory as an optional utility/proximity part only; it is not part of baby-state inference.
- **2026-06-21** — Updated hardware inventory with Mo’s exact component quantities: servos, PCA9685 boards, MAX98357 amplifiers, 3W speakers, INMP441 mics, HC-SR04, VL53L0X, OLEDs, USB-C PD trigger boards, and bench supplies. Added caveats for I²S mics, servo power, HC-SR04 voltage divider, and VL53L0X preference.
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
