#!/usr/bin/env bash
# Gated batch-loop for voice v2 (VC1 chime, VC2 voice soothe control, VC3
# follow-ups, VC4 history questions). codex writes one unit, the driver runs the
# FULL test suite as a gate, then commits + pushes to main. Stops on a blocked unit.

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="/Users/elzekmo/Code/Labie/.claude/worktrees/flamboyant-kilby-76d688"
cd "$REPO" || { echo "repo not found"; exit 1; }

STATE_DIR="$REPO/.smartloop"; LOG_DIR="$STATE_DIR/logs"
LEDGER="$STATE_DIR/voice-v2-units.md"; SUMMARY="$STATE_DIR/VOICE_V2_SUMMARY.md"
SPEC="plans/voice-v2-spec.md"
mkdir -p "$LOG_DIR"

TEST_CMD="pytest -q"
CODEX_TIMEOUT=2400
MAX_RETRIES=2

UNITS=(
  "VC1|feat: chime on wake word so you know it heard you|Add chime.wav (generator) + [assistant] chime_enabled; play a short chime when the wake word is recognised, before answering; don't transcribe it."
  "VC2|feat: full voice control of soothing|Extend match_soothe_command for play-by-name (12 sounds), stop, next/switch, louder/quieter, start/stop cry-guard; wire actions in the cli soothe path."
  "VC3|feat: follow-up questions with light conversation memory|Carry last intent so 'is that hot for a baby?' / 'what about humidity?' resolve deterministically; value always from the sensor read."
  "VC4|feat: history voice questions (cry counts + trends)|Answer 'how many times did she cry tonight?' and 'is it getting colder?' from the persisted history; best-guess trends, no medical claims."
)

log() { echo "[$(date '+%H:%M:%S')] $*"; }
ledger_status() {
  grep -q "^- \[x\] $1 " "$LEDGER" 2>/dev/null && { echo DONE; return; }
  grep -q "^- \[!\] $1 " "$LEDGER" 2>/dev/null && { echo BLOCKED; return; }
  echo TODO
}
ledger_mark() {
  local uid="$1" mark="$2" note="$3"
  grep -v "] $uid " "$LEDGER" > "$LEDGER.tmp" 2>/dev/null || true
  echo "- [$mark] $uid — $note ($(date '+%Y-%m-%d %H:%M'))" >> "$LEDGER.tmp"
  sort "$LEDGER.tmp" -o "$LEDGER"; rm -f "$LEDGER.tmp"
}
[ -f "$LEDGER" ] || { echo "# voice-v2 ledger"; echo; } > "$LEDGER"
run_tests() { eval "$TEST_CMD" > "$LOG_DIR/pytest.last" 2>&1; }
push_main() {
  if git push origin HEAD:main >> "$LOG_DIR/git.log" 2>&1; then return 0; fi
  log "push rejected — fetch+rebase+retry once"
  git fetch origin >> "$LOG_DIR/git.log" 2>&1
  if git rebase origin/main >> "$LOG_DIR/git.log" 2>&1; then
    git push origin HEAD:main >> "$LOG_DIR/git.log" 2>&1 && return 0
  else git rebase --abort >> "$LOG_DIR/git.log" 2>&1 || true; fi
  return 1
}

log "preflight: baseline tests"
run_tests || { log "PREFLIGHT FAIL — baseline red. Aborting."; tail -5 "$LOG_DIR/pytest.last"; exit 1; }
log "preflight green"

for entry in "${UNITS[@]}"; do
  IFS='|' read -r UNIT MSG TASK <<< "$entry"
  st=$(ledger_status "$UNIT")
  [ "$st" = "DONE" ] && { log "$UNIT already DONE — skip"; continue; }
  [ "$st" = "BLOCKED" ] && { log "$UNIT BLOCKED — stopping"; break; }
  attempt=0; landed=0; extra=""
  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    attempt=$((attempt+1)); log "$UNIT attempt $attempt: codex"
    PROMPT="Read $SPEC in this repo IN FULL — it maps the voice loop and the four units with acceptance tests. Implement ONLY unit $UNIT ($TASK). Match existing code/test style. Add the acceptance test(s) the spec requires. Ensure the WHOLE suite passes with: $TEST_CMD . stdlib (+numpy for assets) only — no new dependency. Deterministic; the LLM must never invent facts. When done print one line of what changed.$extra"
    timeout "$CODEX_TIMEOUT" codex exec -s workspace-write \
      --output-last-message "$LOG_DIR/$UNIT.codex.txt" "$PROMPT" \
      > "$LOG_DIR/$UNIT.run.log" 2>&1 || log "$UNIT codex nonzero/timeout"
    log "$UNIT gate: tests"
    if ! run_tests; then
      log "$UNIT tests RED (attempt $attempt)"
      extra=" Previous attempt left failing tests; fix them. pytest tail: $(tail -25 "$LOG_DIR/pytest.last" | tr '\n' ' ')"; continue
    fi
    if [ -z "$(git status --porcelain)" ]; then
      log "$UNIT green but NO changes (attempt $attempt)"
      extra=" The previous attempt changed no files. You MUST edit files to implement $UNIT."; continue
    fi
    git add -A >> "$LOG_DIR/git.log" 2>&1
    git commit -m "$MSG" -m "Built by gated codex voice-v2 loop ($UNIT)." -m "Co-Authored-By: WOZCODE <contact@withwoz.com>" >> "$LOG_DIR/git.log" 2>&1
    if push_main; then ledger_mark "$UNIT" "x" "$MSG"; log "$UNIT DONE + pushed"; landed=1
    else ledger_mark "$UNIT" "!" "tests green, commit local, PUSH FAILED"; log "$UNIT push failed — stopping"; landed=2; fi
    break
  done
  [ "$landed" = "0" ] && { ledger_mark "$UNIT" "!" "could not go green after $((MAX_RETRIES+1)) attempts"; log "$UNIT BLOCKED — stopping"; break; }
  [ "$landed" = "2" ] && break
done

{ echo "# voice-v2 summary — $(date '+%Y-%m-%d %H:%M')"; echo; echo "## Ledger"; cat "$LEDGER";
  echo; echo "## Recent commits"; git log --oneline -8; } > "$SUMMARY"
log "voice-v2 finished — summary at $SUMMARY"; cat "$SUMMARY"
