# Vision bench: Phase-1 measurement harness for baby-positive detection (stock YOLO, off-Pi)

## Goal
Build the measurement tooling that answers "how well do stock COCO models detect our infant
on real nursery footage?" — a `beddington vision-bench` CLI (collect frames from the live Pi,
analyze them offline with YOLOv8 detect+pose on the LAN computer, produce a labeled recall
report) plus a `vision_probe` worker analyzer that posts live person-detection annotations.
"Done" = all modes work with an injected fake backend under tests, full suite green, zero new
required dependencies.

## Verified facts (ground truth — do not re-derive or second-guess)

### Repo / branch
- Base branch is `rosalind` (HEAD ea989a2). Active code under `src/beddington/`; never touch
  `src/lullaby/`.
- Test gate: run from the worktree root: `/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q`
  (pyproject sets `pythonpath = ["src"]`, `testpaths = ["tests"]`, so the worktree's code is used).

### Worker protocol (src/beddington/worker.py)
- `Annotation(kind: str, detail: str, ts: float | None = None)` frozen dataclass.
- `Analyzer` Protocol: attributes `name: str`; `wants_frame(self, snapshot: dict) -> bool`;
  `analyze(self, snapshot: dict, events: list[dict], frame: bytes | None) -> list[Annotation]`.
- `BUILTIN_ANALYZERS: dict[str, type[Analyzer]]` currently `{"state_change": StateChangeAnalyzer}`;
  `load_analyzer(spec)` instantiates builtins with NO constructor args.
- `PiClient(base_url, token, timeout)` has `get_snapshot() -> dict`, `get_events() -> dict`,
  `get_frame() -> bytes | None` (None on 404/503), `post_annotation(Annotation) -> bool`.
  Client is stdlib-urllib only; keep it that way.
- Server-side constraints on `/annotate`: kind must match `^worker_[a-z0-9_]{1,40}$`; detail max
  2000 chars; rate limit 30 posts per 60 s. `WorkerLoop` already dedups identical
  (kind, detail) pairs within 300 s.

### CLI (src/beddington/cli.py)
- argparse subparsers created at cli.py:85 (`dest="command", required=True`); the `worker`
  subcommand is added at :334 and dispatched at :416 via
  `if args.command == "worker": return _worker_command(args, config)`; `_worker_command` at
  :2800 resolves `--url`/`--token` with fallback to `config.worker` (WorkerConfig has
  `base_url`, `token`? — check `_worker_command` for the exact fallback fields and mirror the
  same resolution logic for vision-bench collect).

### pyproject.toml
- Required deps are minimal (`ai-edge-litert`, `numpy`); optional extras pattern exists
  (`mic`, `ears`, `dev`). Python `>=3.11,<3.15`.

### Ultralytics (runtime-only dependency — NOT available in your sandbox)
- Package `ultralytics` (add as optional extra `vision = ["ultralytics>=8.3,<9"]`).
- Usage: `from ultralytics import YOLO`; `YOLO("yolov8s.pt")` (detection) and
  `YOLO("yolov8s-pose.pt")` (17 COCO keypoints). Both auto-download weights on first call —
  network is needed at runtime on the user's machine, therefore NO test may instantiate the
  real backend, and `ultralytics` must NEVER be imported at module level anywhere.
- Result API: `results = model(source)`; `r.boxes.xyxy`, `r.boxes.conf`, `r.boxes.cls`,
  `model.names` (COCO: class 0 == "person"); pose results add `r.keypoints.data`
  (N×17×3 tensors: x, y, conf); `r.save(filename=...)` writes an annotated image.
  `YOLO()` accepts a file path as source; for raw JPEG bytes write to a NamedTemporaryFile
  with suffix `.jpg` inside the backend.

### Product rules (from repo CLAUDE.md emergency minimum + SAFETY_COPY)
- Annotation/report language is observational and class-level ONLY: say "person detected",
  never "baby"/"adult" (stock COCO cannot distinguish), never "safe"/"asleep"/any wellbeing
  claim.
- No frames, model weights, or recordings may be committed. Everything stays LAN-local.

## Files in scope
- NEW `src/beddington/vision_bench.py` — all harness logic.
- NEW `tests/test_vision_bench.py`.
- `src/beddington/worker.py` — add `VisionProbeAnalyzer` + register `"vision_probe"` in
  `BUILTIN_ANALYZERS`. No other changes.
- `tests/test_worker.py` — extend for the new analyzer.
- `src/beddington/cli.py` — add `vision-bench` subcommand + `_vision_bench_command` dispatch.
- `pyproject.toml` — add the `vision` optional extra only.
- `docs/COMPUTER-WORKER.md` — short new section documenting vision-bench + vision_probe.

## Design (keep it this simple)
`vision_bench.py`:
- `Detection` dataclass: `label: str`, `confidence: float`, `box: tuple[float, float, float, float]`
  (pixel xyxy), `keypoints: list[tuple[float, float, float]] | None = None`.
- `FrameResult` dataclass: `detections: list[Detection]` (from detect model),
  `poses: list[Detection]` (from pose model, with keypoints), `image_w: int`, `image_h: int`,
  `inference_ms: float`.
- `VisionBackend` Protocol: `analyze_jpeg(self, data: bytes) -> FrameResult` and
  `save_annotated(self, data: bytes, out_path) -> None` (may no-op).
- `UltralyticsBackend(det_model="yolov8s.pt", pose_model="yolov8s-pose.pt", conf=0.25)` —
  lazy import inside `__init__`; on ImportError raise RuntimeError telling the user to
  `pip install 'beddington-monitor[vision]'`.
- `collect_frames(client, out_dir, interval_s, duration_s, *, clock=time.time, sleep=time.sleep)`
  → saves `frame_<unix_ts>.jpg`, appends to `frames.jsonl` lines
  `{"file", "ts", "baby_state", "label", "target_count"}` (fields read defensively from the
  snapshot; missing → null). `get_frame()` returning None is counted and skipped, not fatal.
  Returns a small summary dict (frames saved, misses).
- `analyze_dir(backend, frames_dir, out_path, annotate_dir=None)` → for each `*.jpg` sorted,
  write one JSON line `{"file", "w", "h", "inference_ms", "detections": [...], "poses": [...]}`
  (dataclasses → plain dicts). If `annotate_dir` is set, call `save_annotated` per frame.
- `write_labels_template(frames_dir, out_csv)` → CSV `file,truth` with truth left empty; the
  human fills truth ∈ {baby, adult, both, none, unsure}.
- `write_report(detections_path, labels_path, out_md)` → markdown report: total frames; frames
  with ≥1 person detection (label == "person"); when labels are provided, per-truth-class
  person-detection rate — the headline number is detection rate on `truth == baby` frames;
  confidence distribution buckets; box-height-fraction (box height / image h) distribution;
  hour-of-day breakdown parsed from `frame_<ts>.jpg` filenames; count of poses with ≥1 keypoint
  conf ≥ 0.5. Labels file optional (report still works without truth breakdown).

`VisionProbeAnalyzer` (worker.py):
- `name = "vision_probe"`. Constructor: `(backend: VisionBackend | None = None,
  min_interval_s: float = 30.0, clock=time.monotonic)`; when `backend` is None, construct
  `UltralyticsBackend()` lazily on FIRST use inside `analyze` (so `load_analyzer` and
  `wants_frame` never import ultralytics).
- `wants_frame(snapshot)` → True only when `clock() - last_frame_at >= min_interval_s`.
- `analyze(...)`: frame None → []. Run backend; compute person count and max box-height
  fraction. Post `Annotation(kind="worker_person_seen", detail=...)` ONLY when the observation
  changes vs the previous one (person count bucket or presence flips) — e.g. detail
  `"person x2 (max conf 0.87, max box height 0.62)"` or `"no person detected"`. Respect the
  observational-language rule.

CLI: `beddington vision-bench --mode {collect,analyze,labels-template,report}` with flags
`--url --token --out --interval --duration --frames --detections --labels --annotate --report-out`
(only the ones each mode needs; error clearly when a required flag for the mode is missing).
Mirror `_worker_command`'s url/token config fallback for collect mode. The command function
stays a thin wrapper over `vision_bench` functions.

## Constraints
- `ultralytics` import ONLY inside `UltralyticsBackend` (and nothing else heavier: no cv2, no
  PIL, no torch imports in our code).
- Core/required dependencies unchanged; worker/vision code paths must degrade with a clear
  error message, not a crash, when the extra isn't installed.
- Match existing code style: stdlib, dataclasses, dependency-injected clock/sleep for
  testability, logging via module LOGGER, type hints as in worker.py.
- Tests: NO network, NO ultralytics — fake backend + fake PiClient; JPEG fixtures may be
  arbitrary bytes since the fake backend never decodes them. Cover: collect loop (frames +
  jsonl + miss counting), analyze_dir output shape, labels template, report math (with and
  without labels, including the truth==baby rate), analyzer throttling via fake clock,
  annotation only-on-change behaviour, and the missing-ultralytics RuntimeError message.

## Acceptance
- `/Users/elzekmo/Code/Labie/.venv/bin/python -m pytest -q` green from the worktree root —
  full existing suite plus the new tests.
- `beddington vision-bench --mode report` produces a readable markdown file on synthetic
  detections in a test.
- No module-level ultralytics/cv2/PIL imports anywhere (grep-clean).

## Non-goals
- NO Hailo/HEF/hailort code, NO model fine-tuning or training code.
- NO changes to `live_snapshot.py`, `episodes.py`, `liveview.py` endpoints, `config.py`, or
  any state-machine/copy behaviour.
- NO posture classification, NO baby-vs-adult claims — this phase only measures stock "person"
  detection.
- NO committed model weights, images, or captured frames.

## GUARDS (non-negotiable)
- Write ONLY inside this worktree. Do NOT run any git command (no add/commit/branch/push).
- Do NOT edit files outside "Files in scope".
- If a check can't pass or a fact can't be confirmed, STOP and report — never work around it.
