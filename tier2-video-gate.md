# Tier 2 video gate

> Live status is still in [memory.md](memory.md). This file records the Tier 2
> video boundary so implementation can move without weakening privacy or safety.

## Decision

Mo authorised moving directly to the next steps on 2026-06-23. That clears
**Tier 2A: bench-only local video plumbing**.

Tier 2A may:

1. detect the attached Pi Camera Module 3;
2. capture a short local test frame on the Pi;
3. inspect existing local JPEG/PNG files for hardware-free tests;
4. write derived image metadata such as dimensions, byte count, camera summary,
   and capture metadata keys;
5. compare local PGM/PPM test frames for deterministic visual-change metrics;
6. delete raw test frames by default.

Tier 2A must not:

1. run overnight nursery capture;
2. use video to trigger or suppress parent notifications;
3. claim the baby is safe, asleep, breathing normally, face clear, or covered;
4. send raw frames or video off-device;
5. commit raw camera images;
6. mount camera hardware near the cot without the mount and cable review.

## Privacy plan

Raw frames stay on the Pi. The default smoke command deletes its test frame
after extracting derived metadata. If a developer deliberately keeps a local
test frame, it must stay under gitignored generated-output paths and must not
be copied off-device or committed.

Only derived observations may enter logs. Examples:

- `image_width`
- `image_height`
- `byte_count`
- `camera_summary`
- `metadata_keys`
- later, local-only derived observations such as `motion_score` or
  `visible_agitation_best_guess`

Cloud LLM polish may receive only short derived text. It never receives raw
frames or video.

## False-alarm plan

Video starts as supporting context only. It cannot notify a parent by itself
and cannot cancel an audio-driven notification.

If audio and video disagree, Lullaby should keep checking or notify the parent.
It must not say the baby is safe. Future video wording must stay in this style:

- Allowed: "movement was not detected in the sampled frame window"
- Allowed: "visible agitation best guess"
- Not allowed: "the baby is asleep"
- Not allowed: "the baby is safe"
- Not allowed: "breathing normally"

## Mount and cable plan

Bench tests may run with the camera already attached to the Pi. Nursery use is
not cleared until there is a physical mount plan that keeps:

1. the Pi and Hailo in a vented base;
2. the camera stable and outside the cot;
3. all cables out of reach;
4. all small parts away from the sleep surface;
5. the companion beside the cot, never in the cot.

## Dark-room decision

The attached Camera Module 3 is suitable for daylight bench work. It is not the
dark-room solution. Dark-room video remains blocked until Mo decides whether to
buy and safely mount:

1. a NoIR camera module; and
2. suitable IR illumination.

No night-vision claims or nursery deployment should be built before that
hardware decision.

## Tier 2A acceptance

On a laptop:

1. inspect a local test JPEG/PNG without camera hardware;
2. write `camera-smoke.json` with derived metadata only;
3. pass the hardware-free test suite.

On the Pi:

1. run `rpicam-hello --list-cameras`;
2. run `lullaby camera-smoke --output output/pi-camera-smoke`;
3. see a JSON report with camera/image metadata;
4. confirm the raw test frame is deleted by default.

## Status

Complete as of 2026-06-23. `lullaby camera-smoke` passed locally and on the Pi.
The Pi report identified the attached `imx708` camera, recorded 640×480 JPEG
metadata, and left only `camera-smoke.json` in the output directory.

`lullaby visual-change` also passed locally and on the Pi using generated PGM
test frames. It writes only derived change metrics and uses bounded wording:
`visual_change_detected` or `little_visual_change_detected`.

Next: connect the visual-change metric to two short Pi camera bench captures
while deleting raw frames by default. Do not use video as a notification source
or safety suppressor.
