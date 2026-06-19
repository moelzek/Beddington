# ARCHIVED — Flomotion hand-off — 2026-06-13 (Day 0)

> Lab Witness is retired. This hand-off prompt is preserved for historical reference only and is not active Lullaby hardware guidance.

**Purpose:** kickoff prompt to start the Lab Witness build with Flomotion (external hardware oracle). Scope = get from boxed kit → camera reliably seeing the bench. Beginner-level, one step at a time (Mo is new to hardware + ADHD).

## Open hardware decisions folded into the prompt
1. **Camera cable** — Camera Module 3 ships a wide (15-pin) cable; Pi 5 uses a narrower 22-pin socket → almost certainly needs a Pi-5 camera adapter cable (22-pin→15-pin). Resolve in person while mentors/shops are available.
2. **Screen** — full-size HDMI cable won't fit the Pi 5's micro-HDMI sockets → micro-HDMI adapter OR run headless from laptop. Pick lowest-friction path.
3. **AI HAT+** — not owned. Decide whether CPU-only (OpenCV/MediaPipe) is enough for a high-contrast labware + timing v0, or whether the accelerator is genuinely needed. Inventory leans CPU-first; Flomotion to give a reasoned recommendation. (Also note: locked compute gate in memory.md says Pi 5 8GB + AI HAT+; reality is Pi 5 4GB + no HAT+ — gate needs reconciling with Mo.)

## Paste-ready prompt

```text
You are my hardware build assistant. I'm a beginner with hardware and I have ADHD, so give me ONE step at a time, in plain English, and wait for me to say "done" before moving on. Assume I know nothing. No jargon — if you must use a technical word, explain it in a few words.

PROJECT — "Lab Witness"
I'm building a small camera rig for a 7-day hackathon. A Raspberry Pi with a camera sits above a lab bench, watches a scientist do a simple pipetting task (a serial dilution with one timed mixing/incubation step), and then:
  - automatically writes up what happened as a lab-notebook entry (sent to Notion), and
  - flags when a timed step runs too long or too short.
The only deadline that matters is an ugly-but-working end-to-end demo by 20 June. Right now I just need the rig to reliably SEE the bench. Nothing moves — no robot arms.

HARDWARE I HAVE IN HAND (boxed, with me right now):
  - Raspberry Pi 5, 4GB
  - Official Raspberry Pi 27W USB-C power supply (UK plug)
  - Active Cooler for the Pi 5
  - 2x Raspberry Pi Camera Module 3 (autofocus)
  - SanDisk 32GB microSD card (blank)
  - Rainbow jumper wires, 2-3 breadboards
  - 3x 0.91-inch OLED displays (4 pins: GND, VCC, SCL, SDA)
  - A small speaker (BS-16)
  - A full solder bench (soldering iron, hot-air station, 2 multimeters, hook-up wire)
  - A 6-pin sensor breakout I can't identify (maybe a distance sensor) — ignore for now
  - A micro servo + PCA9685 driver + USB microphone — ignore, not for this version

THREE THINGS I'M UNSURE ABOUT — please address each clearly:
  1. CAMERA CABLE: the Camera Module 3 came with a wide ribbon cable. I've heard the Pi 5 uses a narrower camera socket and may need a different "Pi 5 camera cable" (22-pin to 15-pin). How do I check in 30 seconds, and exactly what do I buy if it doesn't fit? I'm in person right now with mentors and shops nearby, so if I likely need it, tell me immediately so I can sort it before I leave.
  2. SCREEN: my HDMI cable is full-size on both ends, but I'm told the Pi 5 has tiny "micro-HDMI" sockets. Should I get a micro-HDMI adapter, or skip the monitor and run the Pi from my laptop instead? Recommend the EASIEST path for a beginner working alone.
  3. AI ACCELERATOR: I do NOT have the Raspberry Pi AI HAT+ add-on. For a simple job — spotting high-contrast labware and timing one step — do I actually need it, or can the Pi 5 do the vision on its own? Give me a clear recommendation with your reasoning. I don't want to buy or wait for hardware I don't need.

WHAT I WANT FROM YOU NOW:
  - A simple, ordered, step-by-step path from "boxed kit" to "the camera shows a live picture of the bench on a screen." Start at the very first step.
  - Tell me which steps I can do alone tonight, and which I should do NOW while I have mentors and a 3D printer.
  - CAMERA HOLDER: I have a 3D printer for the next few hours only. Suggest a simple way to mount the camera pointing straight down at the bench at a fixed height — a printable design, or an easy improvised rig if that's faster.
  - Flag clearly anything that could damage a part, or that I should double-check with a mentor.
  - Go ONE step at a time and wait for my "done."

Start with step 1.
```

## After Flomotion replies
Bring its Step 1 back into the orchestrator chat for a sanity-check before acting. Risky/uncertain hardware calls → escalate to on-site mentors (robotics founders).
