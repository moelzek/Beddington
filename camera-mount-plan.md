# Camera mount and cable-routing plan

> Tier 2A physical gate. This plan must be satisfied before any nursery camera
> use. It does not approve overnight video features, face-covered observations,
> Hailo inference, night vision, or any safety claim.

## Decision

Nursery video is **not cleared yet**. The current approval remains bench-only
camera work. A nursery test may happen only after a physical mock-up passes the
checks below.

## Safety basis

- CPSC guidance for baby monitor cords says all cords and monitor parts must be
  kept out of reach and at least 3 feet away from the sleep space.
- AAP safe-sleep guidance keeps the sleep area bare: firm, flat surface, fitted
  sheet only, and no extra objects in the crib.
- Raspberry Pi camera documentation says to shut down and disconnect power
  before camera-cable work, seat the cable straight, and avoid sharp bends.
- Camera Module 3 standard variants filter infrared light; dark-room work needs
  a separate NoIR plus IR-illumination decision.

Sources:

- [CPSC baby monitor cord warning](https://www.cpsc.gov/Newsroom/Video/Baby-Monitor-Cords-Have-Strangled-Children)
- [AAP safe sleep guidance](https://www.healthychildren.org/English/ages-stages/baby/sleep/Pages/a-parents-guide-to-safe-sleep.aspx)
- [Raspberry Pi camera documentation](https://www.raspberrypi.com/documentation/accessories/camera.html)

## Required geometry

Use a strict exclusion zone:

1. No camera, Pi, power supply, mount, cable, strap, tape tail, or loose part may
   be inside the cot, attached to cot rails, or within 3 feet of any part of the
   cot, bassinet, play yard, or sleep surface.
2. The camera must view the cot from outside that 3-foot zone.
3. The Pi and any Hailo hardware must stay in a separate vented base, never in a
   plush toy, cot, bassinet, or enclosed fabric space.
4. The companion may sit beside the cot only if it is outside reach and has no
   cable path into the sleep area.

If the camera cannot get a useful view from outside the exclusion zone, the
correct answer is to stop and change the mount/hardware, not to move hardware
closer to the cot.

## Mount requirements

The first nursery candidate should be one of:

1. a wall-mounted bracket outside the exclusion zone;
2. a high shelf or dresser mount outside the exclusion zone, with anti-tip
   restraint for the furniture if needed;
3. a freestanding tripod or stand outside the exclusion zone, weighted and
   blocked so it cannot fall toward the cot.

Do not use:

1. cot-rail clamps;
2. flexible arms that can sag into reach;
3. adhesive-only mounts above or near the sleep surface;
4. any mount with detachable small parts near the sleep area;
5. loose fabric, plush housings, or cable ties inside the cot.

The camera board needs a rigid enclosure or bracket so the PCB and ribbon cable
are not exposed to grabbing, bending, or sharp strain.

## Cable route

Route cables as if the baby can eventually stand and reach further than expected:

1. Keep every cable outside the 3-foot exclusion zone.
2. Run power and camera cables down the wall or back of furniture, not across
   open air.
3. Put cables in a closed cable raceway or conduit wherever a child could touch
   them.
4. Add strain relief at the Pi and camera ends so cable tension cannot pull on
   connectors.
5. Leave no loops, dangling slack, or reachable tails.
6. Keep mains power and adapters away from the cot and off the floor near the
   sleep area.

The Pi 5 camera ribbon is fragile and should not be sharply bent. If the
existing ribbon cannot support a safe route, do not extend it across the sleep
area. Move the whole vented base/camera assembly farther away, or choose a
different camera architecture later.

## Vented base

The base must:

1. hold the Pi 5, active cooler, PSU connection, and any future Hailo hardware;
2. have unobstructed air intake and exhaust;
3. avoid fabric covers and plush stuffing;
4. be stable against tipping or sliding;
5. keep all ports and cable strain-relief points inaccessible to the baby;
6. pass a bench thermal check before any long nursery run.

For the first thermal check, run the intended camera/audio workload on the bench
and log Pi temperature periodically. Stop if the enclosure, PSU, or cables feel
hot, smell unusual, or the Pi throttles.

## Daylight versus dark-room decision

The attached Camera Module 3 is suitable for daylight bench testing. It is not
the night-vision answer.

Before any dark-room nursery test, decide whether to buy and safely mount:

1. a Camera Module 3 NoIR variant; and
2. IR illumination that is physically secure, outside reach, and not marketed or
   documented as a medical/safety monitor.

Until that decision is made, Lullaby must not claim to support night video.

## Allowed first nursery smoke test

Only after the mock-up passes the physical checks:

1. Place the camera and base in the proposed location with the baby absent.
2. Confirm all parts and cables remain outside the 3-foot exclusion zone.
3. Run `lullaby camera-smoke --output output/nursery-camera-smoke`.
4. Run `lullaby camera-change --output output/nursery-camera-change`.
5. Confirm outputs contain only derived JSON reports.
6. Delete any deliberately retained frames.

No baby-state interpretation is allowed in this smoke test.

## Blockers

Do not proceed to nursery video if any item is true:

1. any hardware or cord is within 3 feet of the sleep space;
2. the camera must attach to the cot to get a useful view;
3. any cable hangs, loops, or can be pulled;
4. the Pi/Hailo base is enclosed in fabric or runs warm in a bench test;
5. the mount depends only on adhesive above or near the sleep surface;
6. dark-room video is required but NoIR/IR hardware has not been decided;
7. wording implies the system verifies safety, sleep, breathing, or face
   covering.

## Definition of done

The physical gate is complete only when:

1. Mo chooses the actual location and mount type;
2. photos or a sketch show the camera, Pi base, power, and cable route;
3. the 3-foot exclusion zone is marked;
4. the cable route has strain relief and no reachable slack;
5. a bench thermal check passes;
6. a baby-absent nursery smoke test writes only derived JSON reports.
