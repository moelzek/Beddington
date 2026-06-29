#!/usr/bin/env bash
# Overnight gated batch-loop: codex writes one unit, the driver gates with the
# full test suite, then commits + pushes to main. Stops on a blocked unit.
# Resumable: re-run and it continues at the next non-DONE unit.
#
# NOT a ralph loop. Each unit is independently gated; a unit that can't go green
# after 2 retries stops the whole loop instead of snowballing.

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

REPO="/Users/elzekmo/Code/Labie/.claude/worktrees/flamboyant-kilby-76d688"
cd "$REPO" || { echo "repo not found"; exit 1; }

STATE_DIR="$REPO/.smartloop"
LOG_DIR="$STATE_DIR/logs"
LEDGER="$STATE_DIR/units.md"
SUMMARY="$STATE_DIR/SUMMARY.md"
SPEC="plans/smart-upgrades-spec.md"
mkdir -p "$LOG_DIR"

TEST_CMD="pytest -q"
CODEX_TIMEOUT=2400          # 40 min hard cap per codex call
MAX_RETRIES=2              # attempts = 1 + MAX_RETRIES

# Unit table: "UID|commit message|one-line task". Detail lives in the spec.
UNITS=(
  "U1|feat: soothe outcomes table in SensorStore|Add soothe_outcomes table + append_soothe_outcome + outcomes_since."
  "U2|feat: best-preset soothe-memory logic|Add pure src/beddington/soothe_memory.py best_preset() with exploration + default."
  "U3|feat: record soothe outcomes during a run|On soothe resolve, write success/failure outcome via SensorStore in the run loop."
  "U4|feat: auto-soothe picks the best-remembered sound|Use soothe_memory.best_preset in _AutoSootheWatcher.feed when learning is on."
  "U5|feat: config for soothe learning|Add [soothe.learn] enabled/min_samples config + loader + TOML + validation."
  "U6|feat: cross-night aggregates in SensorStore|Add deterministic last-N-nights stir-times + per-sound tallies query."
  "U7|feat: night-digest trend lines|Add 'usually stirs ~Xam' + 'when X played she quieted k/n' (best guess) lines."
  "U8|feat: optional llama intent translator|Add src/beddington/intent.py translate_intent(), fallback-safe, value-free."
  "U9|feat: wire llama translator into answers|Use translator only on fallback; value always from deterministic brain; off by default."
)

log() { echo "[$(date '+%H:%M:%S')] $*"; }

ledger_status() { # $1=UID -> prints DONE/BLOCKED/TODO
  grep -q "^- \[x\] $1 " "$LEDGER" 2>/dev/null && { echo DONE; return; }
  grep -q "^- \[!\] $1 " "$LEDGER" 2>/dev/null && { echo BLOCKED; return; }
  echo TODO
}

ledger_mark() { # $1=UID $2=mark(x/!) $3=note
  local uid="$1" mark="$2" note="$3"
  grep -v "] $uid " "$LEDGER" > "$LEDGER.tmp" 2>/dev/null || true
  echo "- [$mark] $uid — $note ($(date '+%Y-%m-%d %H:%M'))" >> "$LEDGER.tmp"
  sort "$LEDGER.tmp" -o "$LEDGER"; rm -f "$LEDGER.tmp"
}

if [ ! -f "$LEDGER" ]; then
  { echo "# smart-loop ledger"; echo; } > "$LEDGER"
fi

run_tests() { eval "$TEST_CMD" > "$LOG_DIR/pytest.last" 2>&1; }

push_main() { # returns 0 on success
  if git push origin HEAD:main >> "$LOG_DIR/git.log" 2>&1; then return 0; fi
  log "push rejected — fetch + rebase + retry once"
  git fetch origin >> "$LOG_DIR/git.log" 2>&1
  if git rebase origin/main >> "$LOG_DIR/git.log" 2>&1; then
    git push origin HEAD:main >> "$LOG_DIR/git.log" 2>&1 && return 0
  else
    git rebase --abort >> "$LOG_DIR/git.log" 2>&1 || true
  fi
  return 1
}

# Preflight: clean baseline must be green.
log "preflight: baseline tests"
if ! run_tests; then
  log "PREFLIGHT FAIL — baseline tests red. Aborting."; tail -5 "$LOG_DIR/pytest.last"; exit 1
fi
log "preflight green"

for entry in "${UNITS[@]}"; do
  IFS='|' read -r UID MSG TASK <<< "$entry"
  st=$(ledger_status "$UID")
  if [ "$st" = "DONE" ]; then log "$UID already DONE — skip"; continue; fi
  if [ "$st" = "BLOCKED" ]; then log "$UID BLOCKED — stopping loop"; break; fi

  attempt=0; landed=0; extra=""
  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    attempt=$((attempt+1))
    log "$UID attempt $attempt: codex"
    PROMPT="Read $SPEC in this repo IN FULL — it defines hard constraints, the codebase map, the safety rules, and a numbered unit list. Implement ONLY unit $UID ($TASK). Do not start any other unit. Match existing code and test style. Add or extend tests for this unit. Ensure the WHOLE suite passes with: $TEST_CMD . Stdlib only — no new dependency. No banned words; label inferences (best guess). When done, print one line of what changed.$extra"
    timeout "$CODEX_TIMEOUT" codex exec -s workspace-write \
      --output-last-message "$LOG_DIR/$UID.codex.txt" "$PROMPT" \
      > "$LOG_DIR/$UID.run.log" 2>&1 || log "$UID codex exited non-zero/timeout"

    log "$UID gate: tests"
    if ! run_tests; then
      log "$UID tests RED (attempt $attempt)"
      extra=" Previous attempt left failing tests; fix them. pytest tail: $(tail -25 "$LOG_DIR/pytest.last" | tr '\n' ' ')"
      continue
    fi
    if [ -z "$(git status --porcelain)" ]; then
      log "$UID green but NO changes — codex did nothing (attempt $attempt)"
      extra=" The previous attempt made no file changes. You MUST edit files to implement $UID."
      continue
    fi
    # green + has changes -> commit + push
    git add -A >> "$LOG_DIR/git.log" 2>&1
    git commit -m "$MSG" -m "Built by overnight gated codex loop ($UID)." -m "Co-Authored-By: WOZCODE <contact@withwoz.com>" >> "$LOG_DIR/git.log" 2>&1
    if push_main; then
      ledger_mark "$UID" "x" "$MSG"
      log "$UID DONE + pushed to main"; landed=1
    else
      ledger_mark "$UID" "!" "tests green, commit kept locally, PUSH FAILED (conflict)"
      log "$UID push failed — local commit kept, stopping loop"; landed=2
    fi
    break
  done

  if [ "$landed" = "0" ]; then
    ledger_mark "$UID" "!" "could not go green after $((MAX_RETRIES+1)) attempts"
    log "$UID BLOCKED after retries — stopping loop"; break
  fi
  if [ "$landed" = "2" ]; then break; fi
done

# Closeout: count how many units landed, smoke-test the CLI, and append a
# local-only changelog line to memory.md (gitignored -> not pushed, by design).
DONE_COUNT=$(grep -c "^- \[x\] " "$LEDGER" 2>/dev/null || echo 0)
log "closeout: $DONE_COUNT unit(s) landed"
beddington --help > "$LOG_DIR/smoke.log" 2>&1 && log "smoke: beddington --help OK" || log "smoke: beddington --help FAILED (see smoke.log)"
if [ -f memory.md ] && [ "$DONE_COUNT" -gt 0 ]; then
  printf -- "- **%s** — Overnight gated codex loop landed %s smart-upgrade unit(s) (soothe memory / night trends / llama translator). See \`git log main\` and \`.smartloop/units.md\`.\n" \
    "$(date '+%Y-%m-%d')" "$DONE_COUNT" >> memory.md
  log "appended local changelog line to memory.md (not committed; file is gitignored)"
fi

# Morning summary
{
  echo "# Overnight smart-loop summary — $(date '+%Y-%m-%d %H:%M')"
  echo
  echo "## Ledger"; cat "$LEDGER"
  echo; echo "## Recent commits on this branch"
  git log --oneline -12
  echo; echo "## Tip: blocked units have [!]; read .smartloop/logs/<UID>.run.log"
} > "$SUMMARY"
log "loop finished — summary at $SUMMARY"
cat "$SUMMARY"
