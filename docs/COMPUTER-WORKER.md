# Computer Worker

The computer worker runs on a LAN machine, polls the Pi live-view server, runs
optional analyzers, and posts observational annotations back to the Pi event
store. It never controls alerts, soothing, mode, or autosoothe.

Start the Pi live view with a scoped worker token:

```bash
beddington live-view --token main-liveview-token --worker-token worker-liveview-token
```

Run the worker from another LAN computer:

```bash
BEDDINGTON_LIVEVIEW_TOKEN=worker-liveview-token \
  beddington worker --url http://pi-hostname-or-ip:8088
```

For a smoke check:

```bash
beddington worker --url http://pi-hostname-or-ip:8088 \
  --token worker-liveview-token --once
```

## Vision Bench

`vision-bench` measures how stock COCO YOLO models report `person` on real
nursery frames. It runs on the LAN computer, keeps frames local, and makes no
identity, sleep, safety, or wellbeing claims.

Collect frames from the Pi live-view server:

```bash
BEDDINGTON_LIVEVIEW_TOKEN=worker-liveview-token \
  beddington vision-bench --mode collect \
  --url http://pi-hostname-or-ip:8088 \
  --out ./vision-frames --interval 5 --duration 600
```

Analyze the frames on the computer with the optional vision extra installed:

```bash
pip install 'beddington-monitor[vision]'
beddington vision-bench --mode analyze \
  --frames ./vision-frames \
  --detections ./vision-frames/detections.jsonl \
  --annotate ./vision-frames/annotated
```

Create a label sheet, fill `truth` with `baby`, `adult`, `both`, `none`, or
`unsure`, then write the report:

```bash
beddington vision-bench --mode labels-template \
  --frames ./vision-frames --labels ./vision-frames/labels.csv
beddington vision-bench --mode report \
  --detections ./vision-frames/detections.jsonl \
  --labels ./vision-frames/labels.csv \
  --report-out ./vision-frames/report.md
```

For a live observational probe, enable the worker analyzer:

```bash
BEDDINGTON_LIVEVIEW_TOKEN=worker-liveview-token \
  beddington worker --url http://pi-hostname-or-ip:8088 \
  --analyzer state_change --analyzer vision_probe
```

`vision_probe` posts only change-based annotations such as `person x1 (...)` or
`no person detected`. It never posts baby-vs-adult, posture, sleep, safety, or
health claims.

Guarantees:

- The worker client has no `/alert`, `/soothe`, `/mode`, or `/autosoothe` methods.
- The scoped worker token can read live-view GET endpoints and post `/annotate`.
- `/annotate` only accepts `worker_` annotation kinds, so remote notes cannot spoof
  native event kinds.
- A Pi without a worker keeps the same live-view behavior.
