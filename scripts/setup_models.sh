#!/usr/bin/env bash
# Load Beddington's local AI model into the device.
#
# The 1.3 GB llama3.2:1b model is NOT stored in git (binary weights are
# gitignored). Instead the repo knows how to *fetch* it: this script pulls it
# once via Ollama so the on-by-default narrator + intent-translator work.
#
# Usage:  bash scripts/setup_models.sh
# Safe to re-run; it skips the pull if the model is already present.

set -euo pipefail

MODEL="${BEDDINGTON_LLM_MODEL:-llama3.2:1b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

echo "Beddington model setup → $MODEL"

# 1. Ensure Ollama is installed.
if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: 'ollama' is not installed."
  echo "  Install it on the Pi / Linux with:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "  Then re-run: bash scripts/setup_models.sh"
  exit 1
fi

# 2. Ensure the Ollama service is reachable (start it if needed).
if ! curl -fsS --max-time 3 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "Ollama service not reachable at $OLLAMA_HOST — starting it in the background..."
  (ollama serve >/dev/null 2>&1 &) || true
  for i in $(seq 1 20); do
    curl -fsS --max-time 2 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 3. Pull the model unless it is already present.
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "✓ $MODEL already present — nothing to pull."
else
  echo "Pulling $MODEL (~1.3 GB, one-time)..."
  ollama pull "$MODEL"
fi

# 4. Confirm.
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "✓ Ready. Beddington's narrator + intent-translator will use $MODEL."
else
  echo "ERROR: $MODEL still not present after pull. Check 'ollama list'."
  exit 1
fi
