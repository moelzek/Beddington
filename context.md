# context.md — Lullaby (WHAT & WHY)

Durable orientation for anyone working on Lullaby. Live status and decisions live in [memory.md](memory.md).

## One-Line Purpose

A privacy-first baby-monitor companion that helps caregivers know when to check the baby, while keeping raw audio/video local and avoiding medical claims.

## Pitch

Most baby monitors stream raw feeds and leave tired parents to interpret everything. Lullaby turns local observations into calm, bounded check prompts: "baby is fussing", "camera view is blocked", "please check". It is a companion, not a clinician.

## Product Boundaries

- **Local-first:** raw audio/video stays on-device.
- **Deterministic-first:** core detection and alerting work without an LLM.
- **Caregiver agency:** alerts prompt a human check; they do not assert safety or danger.
- **No medical claims:** no diagnosis, treatment, SIDS-prevention, breathing-health, or "all clear" guarantees.
- **Safe hardware posture:** hot compute lives in a vented base beside the cot, not inside the cot.

## Domain Terms

- **Observation:** simple local signal from a perceiver, such as sound state, motion state, baby presence, view clarity, or optional room comfort values.
- **Policy:** user-configured duration thresholds for when an observation should become a check prompt.
- **Deterministic alert:** a rule-based prompt that fires without cloud inference.
- **Journal:** local text log of status and check events. It can later be summarised, but raw media is not sent to a cloud model.

## Active Architecture

```text
[Camera/mic/local replay] -> [Perceiver] -> [Observation]
                                      -> [LullabyMonitor deterministic rules]
                                      -> [Local journal]
                                      -> [Caregiver check alert]
```

## What Could Go Wrong

- Hardware gets placed too close to the cot: reject and move compute to a vented base beside the cot.
- Copy drifts into medical reassurance: remove it.
- LLM becomes required for alerts: cut it; deterministic rules must remain primary.
- Raw media leaves the device: block it unless Mo explicitly changes the privacy boundary.
