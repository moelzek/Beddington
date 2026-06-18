# Lullaby

Lullaby is a privacy-first baby-monitor companion that processes audio and, in later tiers, other nursery signals locally. Its first useful job is to aggregate the night into cry events and a readable morning digest; its next is to try a gentle soothe step before escalating. It is an assistive notebook, not a medical guardian: raw audio/video never leaves the device, uncertain interpretations are labelled best guesses, and the complete app works with cloud features disabled.

## Status

The repository has been repivoted from Lab Witness. Tier 0, the hardware-free audio spine, is the active build. Historical Lab Witness material is preserved under `Archive/`.

## Quickstart

The exact install, sample-run, output, and test commands will land with the Tier 0 code. No Raspberry Pi or API key will be required for the laptop quickstart.

## Project documents

- [memory.md](memory.md) — canonical state and decisions
- [baby-monitor-build-plan.md](baby-monitor-build-plan.md) — tiered build plan and BOM
- [baby-monitor-evaluation.md](baby-monitor-evaluation.md) — evaluation and safety gate
- [ROADMAP.md](ROADMAP.md) — active sequence and acceptance gates

## Safety and privacy

Lullaby does not diagnose illness, detect SIDS/apnoea/fever, or replace adult supervision or approved monitoring equipment. Keep any companion beside the cot, never in it, and keep hot compute in a vented base.
