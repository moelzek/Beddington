# skills.md — Lullaby tool routing

> Reach for the smallest tool that advances the active tier. The old Lab Witness reviewer skills are archived and are not part of the Lullaby runtime.

| Situation | Tool or approach |
|---|---|
| Build or refactor Python | Standard library first; small typed modules; `pytest` for behaviour |
| Audio model integration | Official YAMNet/TensorFlow documentation; keep the model behind a detector interface |
| Debug detection | Reproduce with a fixed WAV, log per-window confidence, then tune threshold/sustained duration |
| Pi microphone | `sounddevice` adapter or equivalent, isolated from file-based core logic |
| Camera/Hailo work | Later-tier official Raspberry Pi `picamera2` and Hailo examples |
| Optional cloud prose | Provider-neutral adapter; environment variables only; derived text/features only |
| Secrets/config | `.env.example` plus environment variables; never commit `.env` |
| Logs | Local JSON plus readable text; never include raw audio/video |
| Hardware safety | Stop and escalate to an appropriate human mentor before proceeding |

## Out of scope during Tier 0

- Camera, Hailo, radar, MQTT, OLED, speaker, Notion, phone push, cry-reason classification, hunger inference, and medical-style monitoring.
- Model training. Tier 0 uses a pre-trained detector and tests the surrounding deterministic logic.
