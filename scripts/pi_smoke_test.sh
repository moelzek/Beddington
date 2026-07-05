#!/usr/bin/env bash
set -euo pipefail

CONFIG="config/pi-product.toml"
PORT="8088"
SKIP_ANALYZE=0
SKIP_HTTP=0
PYTHON=".venv/bin/python"
TOKEN_FILE="${HOME}/.config/beddington/liveview.token"
WORKDIR=""

OK_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

usage() {
  printf '%s\n' \
    "Usage: scripts/pi_smoke_test.sh [--config PATH] [--port N] [--skip-analyze] [--skip-http]" \
    "" \
    "End-to-end Raspberry Pi smoke test. It writes only to a temporary workdir." \
    "" \
    "Options:" \
    "  --config PATH    TOML config path (default: config/pi-product.toml)" \
    "  --port N         live-view port (default: 8088)" \
    "  --skip-analyze   skip the offline analyze pipeline smoke" \
    "  --skip-http      skip the live dashboard HTTP smoke" \
    "  --help           show this help"
}

result() {
  local status="$1"
  local check="$2"
  local detail="$3"
  printf '%s %s: %s\n' "$status" "$check" "$detail"
  case "$status" in
    OK) OK_COUNT=$((OK_COUNT + 1)) ;;
    WARN) WARN_COUNT=$((WARN_COUNT + 1)) ;;
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
    SKIP) SKIP_COUNT=$((SKIP_COUNT + 1)) ;;
  esac
}

ok() { result "OK" "$1" "$2"; }
warn() { result "WARN" "$1" "$2"; }
fail() { result "FAIL" "$1" "$2"; }
skip() { result "SKIP" "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { printf 'Missing value for --config\n' >&2; exit 2; }
      CONFIG="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || { printf 'Missing value for --port\n' >&2; exit 2; }
      PORT="$2"
      shift 2
      ;;
    --skip-analyze)
      SKIP_ANALYZE=1
      shift
      ;;
    --skip-http)
      SKIP_HTTP=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

setup_workdir() {
  if ! have mktemp; then
    fail "workdir" "mktemp not found"
    return 1
  fi
  WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/beddington-smoke.XXXXXX")
  if have rm; then
    trap 'rm -rf "$WORKDIR"' EXIT
  else
    warn "workdir cleanup" "rm not found; temporary workdir left at $WORKDIR"
  fi
  ok "workdir" "temporary directory created"
}

choose_stdlib_python() {
  if [[ -x "$PYTHON" ]]; then
    STD_PY="$PYTHON"
  elif have python3; then
    STD_PY="python3"
  elif have python; then
    STD_PY="python"
  else
    STD_PY=""
  fi
}

generate_wav() {
  local wav="$1"
  if [[ -z "${STD_PY:-}" ]]; then
    fail "analyze wav" "no Python interpreter found"
    return 1
  fi
  "$STD_PY" - "$wav" <<'PY' >/dev/null
import math
import struct
import sys
import wave

path = sys.argv[1]
rate = 16000
seconds = 6
frames = []
for index in range(rate * seconds):
    tone = 0.03 * math.sin(2.0 * math.pi * 440.0 * index / rate)
    texture = 0.005 * math.sin(2.0 * math.pi * 37.0 * index / rate)
    sample = int(max(-1.0, min(1.0, tone + texture)) * 32767)
    frames.append(struct.pack("<h", sample))

with wave.open(path, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(rate)
    wav.writeframes(b"".join(frames))
PY
}

json_file_valid() {
  local path="$1"
  local py="${STD_PY:-}"
  [[ -n "$py" ]] || return 2
  "$py" - "$path" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path

with Path(sys.argv[1]).open("r", encoding="utf-8") as file:
    json.load(file)
PY
}

check_analyze() {
  if [[ "$SKIP_ANALYZE" == "1" ]]; then
    skip "analyze" "skipped by flag"
    return
  fi
  local cache_root="${XDG_CACHE_HOME:-$HOME/.cache}"
  local yamnet="${cache_root}/beddington/models/yamnet-classification-tflite-v1.tflite"
  if [[ ! -f "$yamnet" ]]; then
    skip "analyze" "model not downloaded (run: beddington download-model)"
    return
  fi
  if [[ ! -x "$PYTHON" ]]; then
    fail "analyze" "$PYTHON missing or not executable"
    return
  fi
  if [[ ! -f "$CONFIG" ]]; then
    fail "analyze" "$CONFIG missing"
    return
  fi

  local wav outdir analyze_output
  wav="$WORKDIR/synthetic.wav"
  outdir="$WORKDIR/night"
  if generate_wav "$wav"; then
    ok "analyze wav" "generated 6s 16 kHz mono WAV"
  else
    return
  fi

  if analyze_output=$("$PYTHON" -m beddington --config "$CONFIG" analyze "$wav" --output "$outdir" --no-desktop 2>&1); then
    ok "analyze command" "offline analyze exited 0"
  else
    fail "analyze command" "offline analyze exited non-zero"
    return
  fi

  if [[ -f "$outdir/events.json" ]] && json_file_valid "$outdir/events.json"; then
    ok "analyze events" "events.json exists and parses"
  else
    fail "analyze events" "events.json missing or invalid"
  fi
  if [[ -s "$outdir/night-log.txt" ]]; then
    ok "analyze night log" "night-log.txt is non-empty"
  else
    fail "analyze night log" "night-log.txt missing or empty"
  fi
  if [[ -s "$outdir/morning-digest.txt" ]]; then
    ok "analyze digest" "morning-digest.txt is non-empty"
  else
    fail "analyze digest" "morning-digest.txt missing or empty"
  fi
}

http_get_file() {
  local url="$1"
  local output="$2"
  local code
  code=$(curl -sS --max-time 5 -o "$output" -w '%{http_code}' "$url" 2>/dev/null) || code="000"
  HTTP_CODE="$code"
}

json_file_has_keys() {
  local path="$1"
  shift
  local py="${STD_PY:-}"
  [[ -n "$py" ]] || return 2
  "$py" - "$path" "$@" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path

with Path(sys.argv[1]).open("r", encoding="utf-8") as file:
    payload = json.load(file)
missing = [key for key in sys.argv[2:] if not isinstance(payload, dict) or key not in payload]
if missing:
    raise SystemExit(1)
PY
}

jpeg_magic_valid() {
  local path="$1"
  local py="${STD_PY:-}"
  [[ -n "$py" ]] || return 2
  "$py" - "$path" <<'PY' >/dev/null 2>&1
import sys
from pathlib import Path

if Path(sys.argv[1]).read_bytes()[:2] != b"\xff\xd8":
    raise SystemExit(1)
PY
}

check_http_json() {
  local label="$1"
  local path="$2"
  shift 2
  local body="$WORKDIR/${label}.json"
  http_get_file "$path" "$body"
  if [[ "$HTTP_CODE" != "200" ]]; then
    fail "$label" "returned HTTP ${HTTP_CODE:-unknown}"
    return
  fi
  if (($# > 0)); then
    if json_file_has_keys "$body" "$@"; then
      ok "$label" "returned 200 JSON with required keys"
    else
      fail "$label" "JSON missing required keys"
    fi
  elif json_file_valid "$body"; then
    ok "$label" "returned 200 valid JSON"
  else
    fail "$label" "returned invalid JSON"
  fi
}

check_http() {
  if [[ "$SKIP_HTTP" == "1" ]]; then
    skip "http" "skipped by flag"
    return
  fi
  if ! have curl; then
    skip "http" "curl not found"
    return
  fi
  if [[ ! -f "$TOKEN_FILE" ]]; then
    fail "http token" "token file missing; start live-view once to create it"
    return
  fi
  local liveview_secret
  IFS= read -r liveview_secret <"$TOKEN_FILE" || liveview_secret=""
  if [[ -z "$liveview_secret" ]]; then
    fail "http token" "token file is empty"
    return
  fi

  local base="http://127.0.0.1:${PORT}"
  local body="$WORKDIR/snapshot-no-token.json"
  HTTP_CODE=""
  http_get_file "${base}/snapshot.json" "$body"
  if [[ "$HTTP_CODE" == "401" ]]; then
    ok "http snapshot auth" "no-token /snapshot.json returned 401"
  else
    fail "http snapshot auth" "no-token /snapshot.json returned HTTP ${HTTP_CODE:-unknown}"
  fi

  body="$WORKDIR/snapshot.json"
  http_get_file "${base}/snapshot.json?token=${liveview_secret}" "$body"
  if [[ "$HTTP_CODE" == "404" ]]; then
    warn "http snapshot" "no sensor sampler (sensors disabled?)"
  elif [[ "$HTTP_CODE" == "200" ]]; then
    if json_file_has_keys "$body" schema_version baby_state label confidence evidence; then
      ok "http snapshot" "returned 200 JSON with required keys"
    else
      fail "http snapshot" "JSON missing required keys"
    fi
  else
    fail "http snapshot" "returned HTTP ${HTTP_CODE:-unknown}"
  fi

  check_http_json "alerts" "${base}/alerts.json?token=${liveview_secret}" active
  check_http_json "events" "${base}/events.json?token=${liveview_secret}"
  check_http_json "readings" "${base}/readings.json?token=${liveview_secret}"

  body="$WORKDIR/frame.jpg"
  http_get_file "${base}/frame.jpg?token=${liveview_secret}" "$body"
  if [[ "$HTTP_CODE" == "200" ]]; then
    if jpeg_magic_valid "$body"; then
      ok "http frame" "returned JPEG"
    else
      fail "http frame" "HTTP 200 body was not a JPEG"
    fi
  elif [[ "$HTTP_CODE" == "404" || "$HTTP_CODE" == "503" || "$HTTP_CODE" == "000" ]]; then
    warn "http frame" "returned HTTP ${HTTP_CODE:-unknown}; camera frame may be unavailable"
  else
    fail "http frame" "returned HTTP ${HTTP_CODE:-unknown}"
  fi
}

choose_stdlib_python
setup_workdir || true
if [[ -n "$WORKDIR" ]]; then
  check_analyze
  check_http
else
  skip "analyze" "no temporary workdir"
  skip "http" "no temporary workdir"
fi

printf 'SUMMARY OK=%d WARN=%d FAIL=%d SKIP=%d\n' "$OK_COUNT" "$WARN_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"
if (( FAIL_COUNT > 0 )); then
  exit 2
elif (( WARN_COUNT > 0 )); then
  exit 1
fi
exit 0
