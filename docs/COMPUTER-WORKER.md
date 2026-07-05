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

Guarantees:

- The worker client has no `/alert`, `/soothe`, `/mode`, or `/autosoothe` methods.
- The scoped worker token can read live-view GET endpoints and post `/annotate`.
- `/annotate` only accepts `worker_` annotation kinds, so remote notes cannot spoof
  native event kinds.
- A Pi without a worker keeps the same live-view behavior.
