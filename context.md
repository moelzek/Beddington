# context.md — Lab Witness (the WHAT & WHY)

> Durable orientation for any session or sub-agent working on this project. Pairs with [agents.md](agents.md) (how to operate), [skills.md](skills.md) (which tools), and [memory.md](memory.md) (live facts & state).

## Purpose (one line)

A Raspberry Pi over the bench that watches a scientist work, silently writes the lab notebook for them, and flags when reality drifts from the protocol.

## Pitch (the framing, not "a camera that logs pipetting")

> *Lab Witness is the missing sensor for the self-driving lab — the thing that watches the bench so discovery agents can trust the data. It passively documents a human scientist and catches protocol errors, cheaply, with no robots and no typing.*

## Who's involved

- **Mo (owner)** — physician-scientist, owns the science and the story. **New to hardware**; ADHD; recently had a newborn. Has stood at the bench, which is the unfair advantage: he knows exactly which protocol steps go undocumented and which deviations matter.
- **CV / embedded dev (to recruit, Day 0)** — owns the Pi rig end-to-end. **Non-negotiable hire**: they carry week two when Mo's attention collapses. Optionally one generalist. Max three people.
- **Flomotion** (flomotion.app) — a separate AI assistant Mo uses as the primary hardware oracle. Claude does **not** replace it (see [agents.md](agents.md)).
- **Robotics-company founders** — physically present as mentors at the sprint; the escalation path for risky/uncertain hardware calls.
- **Venue / event** — LocalGlobe (Demo Night host). Frontier Biotech is a separate event mid-sprint that collapses Mo's attention.

## Domain concepts & definitions

- **v0** — the ugly-but-working end-to-end demo. The only thing that matters by 20 Jun.
- **The chosen protocol** — a **serial dilution / pipetting series** with one mix/incubation step. Picked for visual distinctness, repeatability and a built-in timing hook.
- **Deviation (v0 scope)** — **timing only**: an incubation/mix step over- or under-running its protocol window. Reagent-order and skipped-step detection are **v2 roadmap only**.
- **Perception → State machine → Decision → Act** — the four-stage pipeline (full diagram in the build doc §3). Labware detection feeds an ordered state machine; a clock checks step duration; actions are a Notion write + a live on-screen flag.
- **The single technical bet** — high-contrast labware is easy to detect, and the step sequence is known and ordered, so a small detector + state machine + clock yields ~80% of the wow for ~20% of the effort.
- **Local-first inference** — detection runs on-device (no faces leave the Pi); a cloud LLM is optional, only for tidying the Notion entry into prose.

## What "good" looks like — the three judging axes

> Canonical rubric lives in [memory.md](memory.md). Confirmed 13 Jun 2026: **Novelty · Deployment · Impact** (supersedes the earlier four-axis framing; "Progress" dropped, "Innovation" → "Novelty"). The build doc §7 still shows the old four — it's a historical snapshot, not the rubric of record.

1. **Novelty** — the white space: self-driving labs automate the *doing* (expensive robots); ELNs need manual *typing*. Almost nobody has built the cheap retrofit that passively watches a *human* and documents them.
2. **Deployment** — a real (or realistic mock) bench is as "in the wild" as physical autonomy gets: perceive → unprogrammed decision → physical-world action. **Highest-risk axis** given the open hardware gaps.
3. **Impact** — the reproducibility crisis. A root cause is that what *actually happened* at the bench is never properly recorded; Lab Witness attacks that directly.

## Milestones / sprint clock

| Date | Milestone |
|---|---|
| **Fri 13 Jun** | Kickoff — Day 0. Lock gates, order kit, recruit dev, write the ordered step-list. |
| **Fri 20 Jun** | **v0 FROZEN** — hard deadline. Clean demo run recorded. Features stop here. |
| **Wed 25 Jun** | Frontier Biotech — attention collapses. No new features. |
| **Sat 28 Jun** | Submission. |
| **Tue 7 Jul** | Demo Night at LocalGlobe (£2k+ prize pool). |

**Organising principle:** *Week two does not exist for you.* Ship an ugly, working v0 by 20 Jun. Weeks after = deployment footage + polish + narrative only.

## Current status snapshot — 13 Jun 2026 (Day 0)

- Both gates **locked** (deployment = mock bench at Blue Garage as spine; protocol = serial dilution; deviation = timing only; compute = Pi 5 4GB + Camera Module 3, **CPU-first (OpenCV/MediaPipe), no AI HAT+ for v0** — HAT deferred, add post-v0 only if CPU too slow).
- **Open Day-0 actions:** order all kit (shipping is the silent killer); recruit/confirm the CV/embedded dev; write the exact ordered step-list for the dilution series.
- No code, rig, or footage exists yet. Build doc is written and is the source of truth: `lab-witness-v0-build-doc.md`.

Live, changing detail (kit order status, dev recruitment, daily progress) lives in [memory.md](memory.md), not here.

## Sources

- Baker, M. "1,500 scientists lift the lid on reproducibility." *Nature* 533, 452–454 (2016). Verified figures: n = 1,576 researchers; **70%** failed to reproduce another scientist's experiments; **>50%** failed to reproduce their own; **~90%** acknowledged a crisis (only 3% said none). [nature.com/articles/533452a](https://www.nature.com/articles/533452a)
- Raspberry Pi AI HAT+ (13 TOPS / Hailo-8L), product brief published Oct 2024 — confirmed: Hailo-8L, 13 TOPS INT8, Pi 5 host, handles object detection / segmentation / pose. *(Deferred for v0 — kept as the post-v0 acceleration option if CPU vision is too slow.)* [Product page](https://www.raspberrypi.com/products/ai-hat/) · [Docs](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html)
- `picamera2` Hailo examples (ship working detection + pose): [github.com/raspberrypi/picamera2](https://github.com/raspberrypi/picamera2)
