> Superseded by the Lullaby baby-monitor pivot on 2026-06-18; retained for history.

# Lab Witness — v0 Build Bible

**One-liner:** A Pi over the bench that watches a scientist work, silently writes the lab notebook for them, and flags when reality drifts from the protocol.

**Demo Night pitch (memorise this, not "a camera that logs pipetting"):**
> *Lab Witness is the missing sensor for the self-driving lab — the thing that watches the bench so discovery agents can trust the data. It passively documents a human scientist and catches protocol errors, cheaply, with no robots and no typing.*

**Sprint clock:** Kickoff 13 Jun · Working v0 hard deadline **20 Jun** · Frontier Biotech 25 Jun (attention collapses) · Submission 28 Jun · Demo Night 7 Jul.

**Organising principle:** Week two does not exist for you. Ship an ugly, working v0 by 20 Jun. Week two = deployment footage + polish + narrative only. Every scoping decision below serves this.

---

## 1. Locked decisions

| Decision | Call | Why |
|---|---|---|
| **Deployment** | Mock bench at Blue Garage as the spine; a friend's real bench as upside B-roll only | Controlled lighting + fixed angle from day one. Real bench never becomes a dependency that can collapse week two. |
| **Protocol** | Serial dilution / pipetting series (one mix/incubation step included) | Most visually distinct, most repeatable, lowest CV risk, guaranteed working v0. Built-in timing hook. |
| **Deviation scope** | **Timing only** for v0 (incubation/mix over- or under-run). Reagent-order & skipped-step → v2 roadmap slide | Timing deviation is nearly free once step-start is detected — a timer keyed to a state change, no extra ML. Still a genuinely "unprogrammed" decision judges can watch fire live. |
| **Compute** | Pi 5 (4GB) + Camera Module 3 + **AI HAT+ 26 TOPS (Hailo-8), on hand & fitted — used for v0 vision** (Hailo-accelerated object detection; state machine + timing on CPU). Cloud LLM for language generation (hybrid allowed) | The HAT is now in hand, so v0 runs real-time Hailo detection — a stronger Deployment + Novelty story than CPU-only. Classical OpenCV on the bare Pi remains the fallback. *(Reverses the earlier CPU-first/no-HAT call — Mo's decision 13 Jun.)* |

---

## 2. v0 scope discipline — what's IN and what's OUT

**IN (the whole v0):**
- One top-down camera over ONE bench, watching ONE dilution series.
- Detect **which step is happening** (labware position/state + simple sequence logic) and **when it starts**.
- Decide: is this step log-worthy? Has the timed step over/under-run its protocol window?
- Act: write a **timestamped entry to Notion** (your lab notebook), and **flag a timing deviation live** (on-screen banner + optional LED/beep).

**OUT (do not build, do not reopen mid-sprint):**
- Recognising "all of lab work." No. One protocol.
- Reagent-order or skipped-step detection. Roadmap only.
- Fine motor / gesture recognition. You lean on labware detection + timing, not hands.
- protocols.io live integration, PubMed/ChEMBL context pulls, discovery-agent hooks. All v2 narrative.
- Multi-bench, multi-user, faces. No.

**The single technical bet:** high-contrast labware (tube rack, tips, reservoir) is *easy* to detect; the step sequence is *known and ordered*; so a small detector + a state machine + a clock gets you 80% of the wow for 20% of the effort.

---

## 3. v0 architecture (hand this to your CV dev)

```
[Top-down camera] 
      │  frames
      ▼
[Perception]  — labware/object detection on the AI HAT+ (Hailo-8): a small detector
                (e.g. YOLO via the picamera2 Hailo examples). Optional MediaPipe
                hand-presence as an "is the scientist active?" gate, NOT for fine action.
      │  detected objects + positions per frame
      ▼
[State machine]  — maps observed state → current protocol step (ordered list of
                   expected steps for THE chosen dilution series). Emits step-start
                   and step-end events with timestamps.
      │  step events
      ▼
[Decision logic]  — (a) log-worthy? → yes on each confirmed step transition.
                    (b) deviation? → step duration vs protocol window (min/max).
      │
      ├──► [Notion]  write timestamped notebook entry (model on your Granola→Notion pipeline)
      └──► [Live flag] on-screen banner + optional LED/buzzer on timing breach
```

**Keep the model small.** Local-first inference (privacy: no faces leave the device). Cloud LLM only for tidying the Notion entry into prose — optional even for that.

---

## 4. Exact kit list (buy today)

| Item | Spec | Approx £ | Note |
|---|---|---|---|
| Raspberry Pi 5 | **4GB (on hand)** | ~£60 | The brain. 4GB is enough for v0. |
| Active cooler + 27W USB-C PSU | Official | ~£20 | Pi 5 throttles without cooling; don't skip. |
| Camera Module 3 | Standard or Wide | ~£25 | Wide if your bench area is large. Autofocus helps. |
| **AI HAT+ (on hand)** | **26 TOPS / Hailo-8** | ~£110 | **Used for v0.** Stacks on the Pi 5; runs the Hailo-accelerated detector. State machine + timing logic stay on the CPU. |
| microSD | 64GB A2 | ~£10 | Flash Raspberry Pi OS (64-bit). |
| Camera cable for Pi 5 | Correct narrow connector | ~£3 | Pi 5 uses a different camera connector — verify you get the Pi-5-compatible cable. |
| **Top-down mount** | Cheap overhead arm / clamp / copy-stand | ~£15–30 | **Single biggest reliability lever.** Fix angle + height early. |
| Controlled light | Small LED panel / ring light | ~£15 | Kill shadows and lighting variance on day one. |
| Optional: LED or buzzer | GPIO indicator | ~£5 | The physical "Act" flourish for the demo. |
| Unused alt: Pi AI Camera (IMX500) | On-sensor detection | ~£70 | Not needed now the AI HAT+ is in hand. On-sensor detection alternative if the HAT route ever fails. |

**Order today.** Shipping is your hidden enemy against a 20 Jun deadline. If anything risks not arriving by ~16 Jun, source locally or have your CV dev bring a spare Pi.

---

## 5. Day-by-day plan to 20 Jun

| Day | Date | Goal — one outcome per day |
|---|---|---|
| 0 | Fri 13 Jun | **Lock the two gates** (done). Order all kit. Recruit/confirm CV dev. Write the exact ordered step-list for your chosen dilution series (your bench intuition — this is the ground truth). |
| 1 | Sat 14 Jun | Flash Pi OS, boot, camera working, run a Hailo-accelerated detection demo on the Pi 5 via the **AI HAT+ (Hailo-8)**. Pure "does the rig see anything" day. |
| 2 | Sun 15 Jun | Build the physical rig: top-down mount fixed, lighting fixed, bench area framed. Record 5–10 clips of the dilution series being performed. This is your dataset + demo footage. |
| 3 | Mon 16 Jun | Perception: reliably detect the key labware (rack, tips, reservoir, tubes). Classical OpenCV first; NPU model only if needed. Output object positions per frame. |
| 4 | Tue 17 Jun | State machine: map detected states → ordered protocol steps. Emit step-start/step-end with timestamps. Get it firing correctly on your recorded clips. |
| 5 | Wed 18 Jun | Action: Notion write working (timestamped entry per step). Decision: timing-deviation flag working (over/under window). **Go/no-go on PCR swap — almost certainly NO, stick with dilution.** |
| 6 | Thu 19 Jun | Integration + live run end-to-end on the real rig. Add the live on-screen banner + LED. Fix the top 3 things that break. |
| 7 | Fri 20 Jun | **v0 FROZEN.** Record the clean demo run. From here: polish + narrative only. Hand the rig to your CV dev. |
| — | 21–28 Jun | Around Frontier Biotech: capture friend's-bench B-roll if available, build Demo Night slides, rehearse the pitch. No new features. |

**ADHD guardrail:** one outcome per day, in order. If a day slips, you cut scope (drop the LED, drop hand-detection, drop cloud-LLM prose) — you do **not** extend into week two.

---

## 6. Top three risks + mitigations

1. **Action-recognition reliability is too low.**
   *Mitigation:* you already scoped around this — labware detection + ordered state machine + timing, not fine motor recognition. If detection is still shaky by Day 4, fall back to classical OpenCV colour/shape on high-contrast labware. The protocol order is known, so the state machine carries you.

2. **Week-two attention collapse (Frontier Biotech, newborn, ADHD).**
   *Mitigation:* v0 frozen 20 Jun; rig owned by your CV dev from Day 7; week two is footage + slides + rehearsal only. The dev owning the hardware is non-negotiable — recruit for that.

3. **Kit / shipping slips past the build window.**
   *Mitigation:* CV dev brings a backup Pi + camera; mock bench means zero dependency on an external lab's calendar. Vision runs on the AI HAT+ (Hailo-8); if the HAT ever fails, classical OpenCV on the bare Pi 5 is the fallback.

*(Honourable mention: lighting/angle variance — fully mitigated by fixing a top-down mount + light panel on Day 2 and never moving them.)*

---

## 7. Why it scores on all four judging axes

- **Innovation:** self-driving labs automate the *doing* (expensive robots); ELNs need manual *typing*. Almost nobody has built the cheap retrofit that passively watches a *human* and documents them. That's the white space.
- **Impact:** the reproducibility crisis. Baker, *Nature* 2016 (n=1,576): >70% of researchers had failed to reproduce another scientist's experiments, >50% their own, ~90% acknowledged a crisis. A root cause is that what *actually happened* at the bench is never properly recorded. Lab Witness attacks that directly. *(Verify the exact figures before quoting on a slide.)*
- **Progress:** a genuine end-to-end v0 is doable on a Pi in the time available — proven by the day-by-day plan above.
- **Deployment:** a real (or realistic mock) bench is as "in the wild" as physical autonomy gets — perceive → unprogrammed decision → physical-world action.

**Your unfair advantage:** you've stood at the bench. You know exactly which protocol steps go undocumented and why. No one else in the room has that intuition — it tells you precisely which step transitions matter and which deviations are worth flagging.

---

## 8. Recruiting one-liner (for your CV/embedded dev)

> *"I'm building the missing sensor for autonomous science — a camera that watches a bench, writes the lab notebook, and catches protocol errors. Deploying it in a real lab in 12 days. I own the science and the story; you own the rig. 2–3 person team, demo night at LocalGlobe, £2k+ prize pool."*

**Who you need:** one strong CV/embedded dev who owns the Pi rig end-to-end (critical — they carry week two). Optionally one generalist. Max three.

---

## 9. v2 roadmap (slide only — do NOT build)

- Reagent-order & skipped-step deviation detection.
- protocols.io as live ground-truth source.
- PubMed / ChEMBL / Open Targets context pulls when something interesting happens.
- The big narrative: *"Lab Witness is the missing sensor for the self-driving lab — the perception layer that watches the bench so FutureHouse/Edison-style discovery agents can trust the data."* (Software agents do the thinking; Lab Witness is the body that makes the data trustworthy.)

---

## 10. The two things to do in the next hour

1. **Order the kit** (Section 4) — shipping is the silent killer.
2. **Write the ordered step-list** for your chosen dilution series — your bench intuition is the ground truth the whole state machine checks reality against. Nobody else can write this.

*Sources for kit/spec verification: [Raspberry Pi AI HAT+](https://www.raspberrypi.com/products/ai-hat/) · [AI HAT+ docs](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html) · [picamera2 Hailo examples](https://github.com/raspberrypi/picamera2). Impact stat: Baker M., "1,500 scientists lift the lid on reproducibility," Nature 533, 452–454 (2016).*
