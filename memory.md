# memory.md — Lullaby (durable FACTS & STATE)

Single source of truth for live project facts. Update this before changing secondary docs.

## Current Canonical Status — 19 Jun 2026

- **Active project:** Lullaby.
- **Repository folder:** `~/Code/Labie`.
- **Pivot decision:** Labie is now Lullaby; Lab Witness is retired and archived.
- **Product:** privacy-first baby-monitor companion.
- **Core promise:** help a caregiver notice when to check the baby, without claiming medical certainty.

## Locked Decisions

| Area | Decision |
|---|---|
| Privacy | Raw audio/video stays on-device. |
| Core behaviour | Deterministic detection and alerting must work with the LLM off. |
| Medical boundary | No diagnosis, treatment, SIDS-prevention, breathing-health, or "baby is safe" claims. |
| Compute placement | Hot compute stays in a vented base beside the cot, not in the cot. |
| Cloud use | Optional only for summarising redacted text events; never raw media. |
| Legacy scope | Lab Witness is archive/reference only. Do not reuse its deadlines or lab-bench requirements. |

## Active V0 Scope

- A local perceiver produces simple observations: presence, motion, sound state, view clarity, optional room comfort signals.
- A deterministic monitor applies configured duration rules.
- A local journal records status changes.
- A caregiver alert says "check baby" when a condition persists beyond the configured window.
- A mock run and tests work without camera hardware.

## Out Of Scope For V0

- Medical advice or risk scoring.
- Sleep-stage detection.
- Breathing-health claims.
- Face identity, cloud video/audio, or multi-user surveillance.
- Reusing Lab Witness lab-protocol, Notion notebook, Hailo/AI HAT, or hackathon deck scope unless explicitly re-approved.

## Open Items

1. Confirm the exact Lullaby v0 demo surface: CLI, local web UI, mobile mock, or hardware rig.
2. Confirm target hardware: laptop-only prototype, Raspberry Pi, phone, or custom base.
3. Write the first Lullaby UX script: what the caregiver sees in a normal night and during a check alert.
4. Decide whether old Lab Witness files should stay as archive, move under `Archive/`, or be removed in a later cleanup.

## Changelog

- **2026-06-19** — Project pivot confirmed by Mo: Labie is now **Lullaby**; **Lab Witness is retired and archived**. Active boundary: privacy-first baby-monitor companion; raw audio/video stays on-device; no medical claims; deterministic detection works with the LLM off; hot compute stays in a vented base beside the cot, not in the cot.
- **2026-06-19** — Active repo pass started: entry docs and Python package migrated from Lab Witness framing to Lullaby framing. Legacy Lab Witness materials remain as archive/reference.
