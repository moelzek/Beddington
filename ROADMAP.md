# ROADMAP.md — Lullaby

Forward plan only. Live decisions live in [memory.md](memory.md).

## Prime Directive

Ship the smallest privacy-first baby-monitor companion that works locally and never makes medical claims.

## V0 Core

| Piece | Done when |
|---|---|
| Local observation model | The app can represent presence, motion, sound state, view clarity, and optional comfort readings. |
| Deterministic monitor | Configured duration rules fire check alerts with the LLM off. |
| Mock demo | `python3 examples/sleep_monitor.py` shows normal status, persistent crying, blocked view, and caregiver check prompts. |
| Tests | Core rules pass with no hardware. |
| Caregiver copy | Alerts say "check baby" and avoid safety/medical guarantees. |
| Hardware boundary | Any physical plan keeps hot compute in a vented base beside the cot. |

## V1 Candidates

- Local web dashboard.
- Camera/mic adapter for a Pi or laptop webcam.
- On-device event summaries from text-only logs.
- Night review timeline for caregivers.
- Enclosure/base design review.

## Explicit Non-Goals

- Medical monitoring or diagnosis.
- SIDS prevention claims.
- Breathing-health verification.
- Cloud raw audio/video.
- Face identity or multi-user surveillance.
- Resurrecting Lab Witness lab-protocol scope.

## Next Few Actions

1. Keep the mock software path green.
2. Decide the first demo surface: CLI, local web UI, or hardware rig.
3. Write the caregiver-facing UX script.
4. Only then choose hardware.
