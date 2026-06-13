# ROADMAP.md — Lab Witness (2-week build → Demo Night)

> Forward plan only. Live status, locked decisions and the roster live in [memory.md](memory.md) — this file *sequences* the work and says **who/what builds each piece**. Pairs with `lab-witness-v0-build-doc.md` (the v0 bible).

> **Timeline revised 13 Jun 2026** — now a two-workshop structure (Workshop #1 Sat 13 Jun · Workshop #2 Sun 21 Jun · demo ≈28 Jun · v0 freeze PROPOSED ~24 Jun). Canonical dates live in [memory.md](memory.md). **TODO (Mo's call):** the day-by-day Tier-A sequence below still reads as a single 13–20 Jun run and needs re-anchoring to the two-workshop structure — not rewritten here.

## Prime directive

**v0 freezes ~24 Jun (PROPOSED — pending Mo's confirmation; was 20 Jun).** Having two weeks does **not** relax that — it just gives the *polish* and *narrative* somewhere to live. Nothing in week two touches the core pipeline. If a day slips, cut scope; never extend the freeze.

Three tiers, in strict order of protection:

- **Tier A — v0 core.** Must ship by the freeze (PROPOSED ~24 Jun). The thing being judged.
- **Tier B — polish.** Week two (21–28 Jun), **only once the core is frozen and working.** Safe because it sits *on top* of the pipeline, never inside it.
- **Tier C — narrative.** Slide only. Not built in these two weeks. The "where this goes next" story.

## Tier A — v0 core (by the freeze, PROPOSED ~24 Jun)

| Piece | Owner | Tool / skill | Components (you own) |
|---|---|---|---|
| Ordered step-list (ground truth) | **Mo** | — | — |
| Pi boot + camera live + OpenCV detection | CV dev | Flomotion (hardware Qs) · `systematic-debugging` · `hardware-reviewer` | Pi 5, Cam Module 3, **adapter cable**, microSD |
| State machine (ordered steps) + timing clock | CV dev | `software-reviewer` | Pi 5 |
| Notion write (timestamped entry) | **Claude** | Notion connector (model on Granola→Notion) | — |
| On-screen deviation banner | CV dev | — | laptop / monitor |
| Fixed rig: top-down mount + light | Mo + dev | Flomotion (mount Qs) | **mount, light** (to buy) |

One camera, one protocol (serial dilution), one error type (timing). That is the whole of v0.

## Tier B — polish (21–28 Jun · only on a frozen core)

Your chosen demo layer, in build order. Each is additive theatre — none touch the core.

| Piece | Owner | Tool / skill | Components (you own) |
|---|---|---|---|
| OLED "now-playing" ticker (step + countdown) | CV dev | Flomotion (I2C wiring) · `hardware-reviewer` | 0.91" I2C OLED ×3, jumpers |
| Green-tick approvals (per correct step) | CV dev / Claude | `software-reviewer` | — (software) |
| Audible chime on deviation | CV dev | Flomotion (speaker wiring) | mini speaker BS-16 |
| Second fixed camera (only if hands occlude) | CV dev | — | 2nd Cam Module 3 (+ **2nd adapter cable**) |
| Friend's-bench B-roll | Mo | — | phone / camera |
| Demo Night deck + visuals | **Claude** | `pptx` · `canvas-design` · `theme-factory` | — |
| Auto-written notebook prose (optional) | **Claude** | Notion + cloud LLM | — |

**Cut order if time-tight:** drop 2nd camera → drop chime → drop OLED → drop auto-prose. **Never cut into Tier A.**

## Tier C — narrative only (slide, do NOT build)

The ideas we pressure-tested and parked. They make a strong "what's next" arc — built into the *deck* by Claude, not into the rig.

- **Wearable / smart-glasses perception** — mobile protocols with no fixed bench. *(LabOS already owns this with XR + cloud; we're the cheap fixed-rig complement, not a clone.)*
- **Watch the robot too** — an independent witness that catches automated liquid-handlers' silent failures (trust-but-verify). Same camera, second job.
- **Tracking / pan-tilt head · multi-bench · multi-user.**
- **Richer deviations** — reagent-order and skipped-step detection (beyond timing).
- **Context pulls** — protocols.io as ground truth; PubMed / ChEMBL / discovery-agent hooks. The full *"missing sensor for the self-driving lab"* story.

## Sprint calendar

> Re-anchored to the two-workshop timeline (revised 13 Jun 2026); canonical dates in [memory.md](memory.md). The per-day Tier-A breakdown still needs re-sequencing — Mo's call (see top-of-file TODO).

| Window | Focus |
|---|---|
| **Sat 13 Jun** | Workshop #1 (in-person build) — kit in hand · assemble rig · write step-list |
| 14–20 Jun | Home / remote tinkering · build Tier A |
| **Sun 21 Jun** | Workshop #2 (in-person integration) |
| ~24 Jun | **v0 FREEZE — PROPOSED** (pending Mo's confirmation) |
| **Wed 25 Jun** | Frontier Biotech — attention collapses · dev carries · no new features *(review — may be superseded; confirm with Mo)* |
| 26–28 Jun | Tier B polish · B-roll · deck · rehearse · **demo ≈28 Jun (approx; LocalGlobe)** |

## Guardrails

- The **CV dev owns the rig from Day 7** — non-negotiable; they carry week two.
- Hardware questions → Flomotion loop; risky calls → on-site mentors. Claude reviews, never decides hardware.
- **Tier B is contingent, not promised:** a working frozen core buys it; a slipping core cancels it.
