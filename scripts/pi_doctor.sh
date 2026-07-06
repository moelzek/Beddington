#!/usr/bin/env bash
set -euo pipefail

CONFIG="config/pi-product.toml"
PORT="8088"
PYTHON=".venv/bin/python"
TOKEN_FILE="${HOME}/.config/beddington/liveview.token"

OK_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

NARRATOR_ENABLED=""
AIR_ENABLED=""
AIR_ADDR_HEX="76"
RADAR_ENABLED=""
RADAR_HOST=""
RADAR_PORT="6053"

LIVEVIEW_STATE="unknown"
ASSISTANT_STATE="unknown"

usage() {
  printf '%s\n' \
    "Usage: scripts/pi_doctor.sh [--config PATH] [--port N]" \
    "" \
    "Read-only Raspberry Pi deployment diagnostic." \
    "" \
    "Options:" \
    "  --config PATH   TOML config path (default: config/pi-product.toml)" \
    "  --port N        live-view port (default: 8088)" \
    "  --help          show this help"
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

disk_check() {
  local path="$1"
  local label="$2"
  if ! have df; then
    skip "$label disk" "df not found"
    return
  fi
  if [[ ! -e "$path" ]]; then
    fail "$label disk" "$path does not exist"
    return
  fi
  local output line filesystem blocks used avail capacity mount
  output=$(df -Pk "$path" 2>/dev/null || true)
  if [[ -z "$output" || "$output" != *$'\n'* ]]; then
    warn "$label disk" "could not read free space for $path"
    return
  fi
  line=${output##*$'\n'}
  read -r filesystem blocks used avail capacity mount <<<"$line"
  if [[ -z "${avail:-}" || ! "$avail" =~ ^[0-9]+$ ]]; then
    warn "$label disk" "could not parse free space for $path"
    return
  fi
  local mb
  mb=$((avail / 1024))
  if (( mb < 500 )); then
    fail "$label disk" "${mb} MB free on $mount"
  elif (( mb < 2048 )); then
    warn "$label disk" "${mb} MB free on $mount"
  else
    ok "$label disk" "${mb} MB free on $mount"
  fi
}

check_system() {
  if have uname; then
    ok "system os" "$(uname -srmo 2>/dev/null || uname -a 2>/dev/null || printf 'unknown')"
  else
    skip "system os" "uname not found"
  fi

  if have uptime; then
    ok "system uptime" "$(uptime 2>/dev/null || printf 'unknown')"
  else
    skip "system uptime" "uptime not found"
  fi

  disk_check "/" "root"
  disk_check "$HOME" "home"

  if [[ -r /proc/meminfo ]]; then
    local total="" available="" key value unit
    while read -r key value unit; do
      case "$key" in
        MemTotal:) total="$value" ;;
        MemAvailable:) available="$value" ;;
      esac
    done </proc/meminfo
    if [[ -n "$total" && -n "$available" ]]; then
      ok "system memory" "$((available / 1024)) MB available of $((total / 1024)) MB"
    else
      warn "system memory" "could not parse /proc/meminfo"
    fi
  elif have sysctl; then
    local bytes
    bytes=$(sysctl -n hw.memsize 2>/dev/null || true)
    if [[ "$bytes" =~ ^[0-9]+$ ]]; then
      ok "system memory" "$((bytes / 1024 / 1024)) MB installed"
    else
      warn "system memory" "could not read memory size"
    fi
  else
    skip "system memory" "no supported memory probe"
  fi

  if have vcgencmd; then
    local temp throttled
    temp=$(vcgencmd measure_temp 2>/dev/null || true)
    throttled=$(vcgencmd get_throttled 2>/dev/null || true)
    if [[ -z "$temp" && -z "$throttled" ]]; then
      warn "system cpu" "vcgencmd did not return temperature or throttle state"
    elif [[ "$throttled" == "throttled=0x0" ]]; then
      ok "system cpu" "${temp:-temp unknown}; $throttled"
    else
      warn "system cpu" "${temp:-temp unknown}; ${throttled:-throttle unknown}"
    fi
  else
    skip "system cpu" "vcgencmd not found"
  fi
}

check_python_env() {
  if [[ -x "$PYTHON" ]]; then
    ok "python executable" "$PYTHON exists"
  else
    fail "python executable" "$PYTHON missing or not executable"
    return
  fi
  if "$PYTHON" -c "import beddington" >/dev/null 2>&1; then
    ok "python import" "import beddington succeeds"
  else
    fail "python import" "import beddington failed"
  fi
}

load_config_flags() {
  [[ -x "$PYTHON" && -f "$CONFIG" ]] || return 1
  local output line key value
  output=$("$PYTHON" - "$CONFIG" <<'PY' 2>/dev/null || true
from pathlib import Path
import sys
from beddington.config import load_config

cfg = load_config(Path(sys.argv[1]))
print(f"NARRATOR_ENABLED={int(bool(cfg.narrator.enabled))}")
print(f"AIR_ENABLED={int(bool(cfg.sensors.air.enabled))}")
print(f"AIR_ADDR_HEX={int(cfg.sensors.air.i2c_address):02x}")
print(f"RADAR_ENABLED={int(bool(cfg.sensors.radar.enabled))}")
print(f"RADAR_HOST={cfg.sensors.radar.host}")
print(f"RADAR_PORT={int(cfg.sensors.radar.port)}")
PY
)
  [[ -n "$output" ]] || return 1
  while IFS='=' read -r key value; do
    case "$key" in
      NARRATOR_ENABLED) NARRATOR_ENABLED="$value" ;;
      AIR_ENABLED) AIR_ENABLED="$value" ;;
      AIR_ADDR_HEX) AIR_ADDR_HEX="$value" ;;
      RADAR_ENABLED) RADAR_ENABLED="$value" ;;
      RADAR_HOST) RADAR_HOST="$value" ;;
      RADAR_PORT) RADAR_PORT="$value" ;;
    esac
  done <<<"$output"
}

check_config() {
  if [[ -f "$CONFIG" ]]; then
    ok "config file" "$CONFIG exists"
  else
    fail "config file" "$CONFIG missing"
    return
  fi
  if [[ ! -x "$PYTHON" ]]; then
    skip "config parse" "$PYTHON missing"
    return
  fi
  if "$PYTHON" - "$CONFIG" <<'PY' >/dev/null 2>&1
from pathlib import Path
import sys
from beddington.config import load_config

load_config(Path(sys.argv[1]))
PY
  then
    ok "config parse" "load_config parsed $CONFIG"
    load_config_flags || warn "config flags" "could not read feature flags"
  else
    fail "config parse" "load_config failed for $CONFIG"
  fi
}

check_models() {
  local cache_root="${XDG_CACHE_HOME:-$HOME/.cache}"
  local yamnet="${cache_root}/beddington/models/yamnet-classification-tflite-v1.tflite"
  if [[ -f "$yamnet" ]]; then
    ok "model yamnet" "cached model exists"
  else
    warn "model yamnet" "missing cached model; first run will download it"
  fi

  if [[ "$NARRATOR_ENABLED" == "0" ]]; then
    skip "model ollama" "narrator disabled in config"
    return
  fi
  if ! have curl; then
    skip "model ollama" "curl not found"
    return
  fi
  local code
  code=$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:11434/api/tags" 2>/dev/null || true)
  if [[ "$code" == "200" ]]; then
    ok "model ollama" "127.0.0.1:11434 is reachable"
  elif [[ "$code" == "000" ]]; then
    warn "model ollama" "127.0.0.1:11434 did not answer"
  else
    warn "model ollama" "127.0.0.1:11434 returned HTTP $code"
  fi
}

check_service() {
  # check_service ROLE STATE_VAR UNIT_CANDIDATE... — uses the first candidate
  # whose user unit file exists (deployed Pis may run legacy-named units).
  local role="$1"
  local state_var="$2"
  shift 2
  local out active candidate unit=""
  if ! have systemctl; then
    skip "service $role" "systemctl not found"
    printf -v "$state_var" '%s' "skip"
    return
  fi
  for candidate in "$@"; do
    out=$(systemctl --user list-unit-files "${candidate}.service" --no-legend 2>/dev/null || true)
    if [[ "$out" == *"${candidate}.service"* ]]; then
      unit="$candidate"
      break
    fi
  done
  if [[ -z "$unit" ]]; then
    skip "service $role" "user unit not installed (tried: $*)"
    printf -v "$state_var" '%s' "skip"
    return
  fi
  active=$(systemctl --user is-active "$unit" 2>/dev/null || true)
  if [[ "$active" == "active" ]]; then
    ok "service $role" "$unit active"
    printf -v "$state_var" '%s' "active"
  else
    warn "service $role" "$unit is-active returned ${active:-unknown}"
    printf -v "$state_var" '%s' "inactive"
  fi
}

liveview_scheme() {
  # live-view records http/https here on startup; the TLS cert is self-signed
  # for the LAN IP, so loopback callers use https with -k (token still gates).
  local scheme_file="$HOME/.config/beddington/liveview.scheme"
  if [[ -r "$scheme_file" ]] && [[ "$(<"$scheme_file")" == "https" ]]; then
    echo "https"
  else
    echo "http"
  fi
}

http_get_text() {
  local url="$1"
  local response code body
  response=$(curl -sSk --max-time 5 -w $'\n%{http_code}' "$url" 2>/dev/null || true)
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  HTTP_CODE="$code"
  HTTP_BODY="$body"
}

json_valid() {
  local body="$1"
  local py=""
  if [[ -x "$PYTHON" ]]; then
    py="$PYTHON"
  elif have python3; then
    py="python3"
  else
    return 2
  fi
  "$py" -c "import json,sys; json.loads(sys.stdin.read())" <<<"$body" >/dev/null 2>&1
}

file_mode() {
  local path="$1"
  if ! have stat; then
    return 1
  fi
  stat -c "%a" "$path" 2>/dev/null || stat -f "%Lp" "$path" 2>/dev/null
}

check_token_file() {
  if [[ ! -f "$TOKEN_FILE" ]]; then
    fail "dashboard token" "token file missing"
    return 1
  fi
  local mode last3
  mode=$(file_mode "$TOKEN_FILE" || true)
  if [[ -z "$mode" ]]; then
    skip "dashboard token permissions" "stat not available"
    return 0
  fi
  last3="${mode: -3}"
  if [[ "$last3" == "600" ]]; then
    ok "dashboard token permissions" "token file mode is 600"
  else
    fail "dashboard token permissions" "token file mode is $last3; expected 600"
  fi
}

check_dashboard() {
  if ! have curl; then
    skip "dashboard http" "curl not found"
    return
  fi

  local base="$(liveview_scheme)://127.0.0.1:${PORT}"
  HTTP_CODE=""
  HTTP_BODY=""
  http_get_text "${base}/alerts.json"
  if [[ "$HTTP_CODE" == "000" ]]; then
    warn "dashboard port" "no HTTP response on 127.0.0.1:$PORT"
    check_token_file || true
    return
  fi
  ok "dashboard port" "HTTP answered on 127.0.0.1:$PORT"

  if [[ "$HTTP_CODE" == "401" ]]; then
    ok "dashboard auth" "no-token /alerts.json returned 401"
  elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "dashboard auth" "no-token /alerts.json returned 200"
  else
    warn "dashboard auth" "no-token /alerts.json returned HTTP $HTTP_CODE"
  fi

  check_token_file || return

  local liveview_secret
  liveview_secret=$(<"$TOKEN_FILE")
  liveview_secret="${liveview_secret%"${liveview_secret##*[![:space:]]}"}"
  if [[ -z "$liveview_secret" ]]; then
    fail "dashboard token" "token file is empty"
    return
  fi

  http_get_text "${base}/alerts.json?token=${liveview_secret}"
  if [[ "$HTTP_CODE" != "200" ]]; then
    fail "dashboard token http" "token-file /alerts.json returned HTTP ${HTTP_CODE:-unknown}"
    return
  fi
  if json_valid "$HTTP_BODY"; then
    ok "dashboard token http" "token-file /alerts.json returned 200 JSON"
  else
    fail "dashboard token http" "token-file /alerts.json did not return valid JSON"
  fi
}

check_hardware() {
  if have rpicam-hello; then
    local cameras
    cameras=$(rpicam-hello --list-cameras 2>&1 || true)
    if [[ "$cameras" == *"No cameras available"* || "$cameras" == *"0 cameras"* ]]; then
      warn "hardware camera" "rpicam-hello found no cameras"
    elif [[ -n "$cameras" ]]; then
      ok "hardware camera" "rpicam-hello listed cameras"
    else
      warn "hardware camera" "rpicam-hello returned no output"
    fi
  else
    skip "hardware camera" "rpicam-hello not found"
  fi

  if have arecord; then
    local microphones
    microphones=$(arecord -l 2>&1 || true)
    if [[ "$microphones" == *"card "* ]]; then
      ok "hardware mic" "arecord listed capture hardware"
    else
      warn "hardware mic" "arecord did not list capture hardware"
    fi
  else
    skip "hardware mic" "arecord not found"
  fi

  if [[ "$AIR_ENABLED" != "1" ]]; then
    skip "hardware air sensor" "disabled in config"
  elif have i2cdetect; then
    local i2c
    i2c=$(i2cdetect -y 1 2>/dev/null || true)
    if [[ " $i2c " == *" ${AIR_ADDR_HEX} "* ]]; then
      ok "hardware air sensor" "I2C address 0x${AIR_ADDR_HEX} present"
    else
      warn "hardware air sensor" "I2C address 0x${AIR_ADDR_HEX} not found"
    fi
  else
    skip "hardware air sensor" "i2cdetect not found"
  fi

  if [[ "$RADAR_ENABLED" != "1" ]]; then
    skip "hardware radar" "disabled in config"
  elif [[ -z "$RADAR_HOST" ]]; then
    warn "hardware radar" "enabled but host is empty"
  elif ! have timeout; then
    skip "hardware radar" "timeout not found for bounded /dev/tcp probe"
  elif RADAR_PROBE_HOST="$RADAR_HOST" RADAR_PROBE_PORT="$RADAR_PORT" timeout 3 bash -c ': </dev/tcp/$RADAR_PROBE_HOST/$RADAR_PROBE_PORT' >/dev/null 2>&1; then
    ok "hardware radar" "$RADAR_HOST:$RADAR_PORT reachable"
  else
    warn "hardware radar" "$RADAR_HOST:$RADAR_PORT not reachable"
  fi
}

mtime_epoch() {
  local path="$1"
  stat -c "%Y" "$path" 2>/dev/null || stat -f "%m" "$path" 2>/dev/null
}

check_log_recent() {
  # check_log_recent LABEL SERVICE_STATE PATH_CANDIDATE... — uses the first
  # log path that exists (legacy deployments use legacy log names).
  local label="$1"
  local service_state="$2"
  shift 2
  local path="$1"
  local candidate
  for candidate in "$@"; do
    if [[ -f "$candidate" ]]; then
      path="$candidate"
      break
    fi
  done
  if [[ "$service_state" == "skip" || "$service_state" == "unknown" ]]; then
    skip "log $label" "service state unavailable"
    return
  fi
  if [[ "$service_state" != "active" ]]; then
    warn "log $label" "service is not active"
    return
  fi
  if [[ ! -f "$path" ]]; then
    warn "log $label" "$path missing"
    return
  fi
  if ! have stat || ! have date; then
    skip "log $label" "stat/date not found"
    return
  fi
  local mtime now age
  mtime=$(mtime_epoch "$path" || true)
  now=$(date +%s 2>/dev/null || true)
  if [[ ! "$mtime" =~ ^[0-9]+$ || ! "$now" =~ ^[0-9]+$ ]]; then
    warn "log $label" "could not read modification time"
    return
  fi
  age=$((now - mtime))
  if (( age <= 600 )); then
    ok "log $label" "$path modified ${age}s ago"
  else
    warn "log $label" "$path modified ${age}s ago"
  fi
}

check_system
check_python_env
check_config
check_models
check_service "liveview" LIVEVIEW_STATE beddington-liveview lullaby-liveview
check_service "assistant" ASSISTANT_STATE beddington-assistant paddington
check_dashboard
check_hardware
check_log_recent "liveview" "$LIVEVIEW_STATE" "${HOME}/liveview.log"
check_log_recent "assistant" "$ASSISTANT_STATE" "${HOME}/beddington-assistant.log" "${HOME}/paddington.log"

printf 'SUMMARY OK=%d WARN=%d FAIL=%d SKIP=%d\n' "$OK_COUNT" "$WARN_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"
if (( FAIL_COUNT > 0 )); then
  exit 2
elif (( WARN_COUNT > 0 )); then
  exit 1
fi
exit 0
